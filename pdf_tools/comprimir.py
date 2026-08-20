"""Reducao de tamanho de PDF, sem depender do Ghostscript.

O notebook original chamava `gs` por subprocess, o que exige instalar um
binario do sistema e nao funciona em qualquer hospedagem. Aqui as tres
estrategias sao Python puro, da mais conservadora para a mais agressiva:

  1. estrutura   - so reescreve o arquivo (nao altera nada do visual)
  2. imagens     - reamostra e recomprime as fotos, preservando texto vetorial
  3. rasterizar  - vira tudo em imagem (ultimo recurso, o texto deixa de ser
                   selecionavel e a busca para de funcionar)
"""

from __future__ import annotations

import io

import img2pdf
import pikepdf
from PIL import Image

from .documento import abrir, salvar
from .imagens import _documento, _escala_segura

# Formatos que ja sao compactos ou que o Pillow nao reescreve com seguranca.
_FILTROS_INTOCAVEIS = {
    "/JPXDecode",
    "/JBIG2Decode",
    "/CCITTFaxDecode",
    "/RunLengthDecode",
}
_AREA_MINIMA = 10_000  # px; icones e linhas nao valem o risco de reencodar
_GANHO_MINIMO = 0.05  # so troca a imagem se economizar ao menos 5%

NIVEIS = {
    "Leve (melhor qualidade)": dict(qualidade=85, lado_maximo=2400),
    "Equilibrado": dict(qualidade=72, lado_maximo=1800),
    "Forte (menor arquivo)": dict(qualidade=55, lado_maximo=1400),
}


def comprimir_estrutura(dados: bytes, senha: str = "") -> bytes:
    """Sem perda: recompacta streams e agrupa objetos.

    Ganha pouco em PDFs modernos e muito em arquivos gerados por Word,
    scanners antigos ou exportadores que nunca comprimiram nada.
    """
    with abrir(dados, senha) as pdf:
        return salvar(
            pdf,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            linearize=True,
        )


def _lista(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, pikepdf.Array):
        return [str(v) for v in valor]
    return [str(valor)]


def _mascaras(pdf: pikepdf.Pdf) -> set[tuple[int, int]]:
    """Objetos usados como mascara de transparencia.

    Recomprimir uma mascara com JPEG cria halos visiveis nas bordas, entao
    esses ficam de fora.
    """
    encontrados: set[tuple[int, int]] = set()
    for obj in pdf.objects:
        try:
            for chave in ("/SMask", "/Mask"):
                alvo = obj.get(chave)
                if alvo is not None and alvo.is_indirect:
                    encontrados.add(alvo.objgen)
        except Exception:
            continue
    return encontrados


def _e_imagem(obj) -> bool:
    try:
        return obj.get(pikepdf.Name.Subtype) == pikepdf.Name.Image
    except Exception:
        return False


def comprimir_imagens(
    dados: bytes,
    *,
    qualidade: int = 72,
    lado_maximo: int = 1800,
    senha: str = "",
    progresso=None,
) -> tuple[bytes, int]:
    """Reamostra e recomprime as imagens embutidas. Retorna (pdf, n_trocadas).

    O texto continua sendo texto: da para selecionar, copiar e buscar.
    """
    with abrir(dados, senha) as pdf:
        protegidos = _mascaras(pdf)
        candidatos = [
            obj
            for obj in pdf.objects
            if isinstance(obj, pikepdf.Stream) and _e_imagem(obj)
        ]
        trocadas = 0
        for posicao, obj in enumerate(candidatos, start=1):
            if obj.objgen not in protegidos and _recomprimir(
                obj, qualidade, lado_maximo
            ):
                trocadas += 1
            if progresso:
                progresso(posicao / max(len(candidatos), 1))

        resultado = salvar(
            pdf,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        return resultado, trocadas


def _recomprimir(obj, qualidade: int, lado_maximo: int) -> bool:
    """Substitui o stream de uma imagem por um JPEG menor. True se trocou."""
    try:
        if obj.get(pikepdf.Name.ImageMask):
            return False  # stencil de 1 bit: JPEG so pioraria
        if set(_lista(obj.get(pikepdf.Name.Filter))) & _FILTROS_INTOCAVEIS:
            return False

        largura = int(obj.get(pikepdf.Name.Width, 0))
        altura = int(obj.get(pikepdf.Name.Height, 0))
        if largura * altura < _AREA_MINIMA:
            return False

        original = len(obj.read_raw_bytes())
        imagem = pikepdf.PdfImage(obj).as_pil_image()
    except Exception:
        # Colorspace exotico, imagem corrompida, indexada rara: nao mexer.
        return False

    try:
        maior_lado = max(imagem.size)
        if maior_lado > lado_maximo:
            fator = lado_maximo / maior_lado
            imagem = imagem.resize(
                (
                    max(1, int(imagem.width * fator)),
                    max(1, int(imagem.height * fator)),
                ),
                Image.LANCZOS,
            )

        cinza = imagem.mode in {"L", "1", "I", "I;16"}
        imagem = imagem.convert("L" if cinza else "RGB")

        buffer = io.BytesIO()
        imagem.save(buffer, "JPEG", quality=qualidade, optimize=True, progressive=True)
        novo = buffer.getvalue()

        if len(novo) >= original * (1 - _GANHO_MINIMO):
            return False

        obj.write(novo, filter=pikepdf.Name.DCTDecode)
        obj.ColorSpace = pikepdf.Name.DeviceGray if cinza else pikepdf.Name.DeviceRGB
        obj.BitsPerComponent = 8
        obj.Width, obj.Height = imagem.width, imagem.height
        for chave in ("/Decode", "/DecodeParms", "/SMaskInData"):
            if chave in obj:
                del obj[chave]
        return True
    except Exception:
        return False


def rasterizar(
    dados: bytes,
    *,
    dpi: int = 120,
    qualidade: int = 70,
    cinza: bool = False,
    senha: str = "",
    progresso=None,
) -> bytes:
    """Converte cada pagina em uma foto JPEG e remonta o PDF.

    Descarta texto selecionavel, links e marcadores - em troca costuma cortar
    boa parte do peso de arquivos escaneados ou cheios de arte vetorial.
    """
    doc = _documento(dados, senha)
    try:
        total = len(doc)
        if total == 0:
            raise ValueError("O PDF não tem páginas.")

        paginas: list[bytes] = []
        for indice in range(total):
            pagina = doc[indice]
            escala = _escala_segura(pagina, dpi)
            imagem = pagina.render(scale=escala).to_pil()
            imagem = imagem.convert("L" if cinza else "RGB")

            buffer = io.BytesIO()
            # O DPI gravado no JPEG e o que faz o img2pdf reconstruir a pagina
            # no tamanho fisico original, em vez de assumir 72 dpi.
            dpi_real = round(72 * escala, 2)
            imagem.save(
                buffer,
                "JPEG",
                quality=qualidade,
                optimize=True,
                progressive=True,
                dpi=(dpi_real, dpi_real),
            )
            paginas.append(buffer.getvalue())
            if progresso:
                progresso((indice + 1) / total)

        return img2pdf.convert(paginas, layout_fun=img2pdf.get_layout_fun())
    finally:
        doc.close()


def diagnostico(dados: bytes, senha: str = "") -> dict:
    """Estima quanto do arquivo e imagem, para sugerir a estrategia certa."""
    with abrir(dados, senha) as pdf:
        bytes_imagem = 0
        contagem = 0
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream) and _e_imagem(obj):
                try:
                    bytes_imagem += len(obj.read_raw_bytes())
                    contagem += 1
                except Exception:
                    continue

        fracao = min(bytes_imagem / max(len(dados), 1), 1.0)
        return {
            "imagens": contagem,
            "bytes_imagem": bytes_imagem,
            "fracao_imagem": fracao,
            "sugestao": "imagens" if contagem and fracao > 0.5 else "estrutura",
        }
