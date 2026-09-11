"""Redimensionamento de imagens pelo tamanho em pixels, uma ou várias de uma vez."""

from __future__ import annotations

import io

from PIL import Image, ImageColor, ImageOps

from .util import Arquivo, nome_base, nome_seguro

# Uma imagem RGBA de 10.000 x 10.000 já ocupa 400 MB de memória; o plano
# gratuito do Streamlit tem 1 GB. Acima disso a aba cai no meio do lote.
LADO_MAXIMO = 10_000

MODOS = ("exato", "largura", "altura", "lado_maior")
ENCAIXES = ("cortar", "fundo", "esticar")
FORMATOS_SAIDA = ("original", "PNG", "JPEG", "WEBP")

_EXTENSOES = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
_ACEITAM_ALFA = {"PNG", "WEBP"}
_TAG_ORIENTACAO = 0x0112  # EXIF: o celular grava a foto deitada e manda girar


def dimensoes_imagem(dados: bytes) -> tuple[int, int]:
    """Largura x altura como a imagem aparece na tela.

    Lê só o cabeçalho, sem decodificar os pixels. Considera o giro do EXIF:
    uma foto em pé tirada no celular costuma estar gravada deitada.
    """
    with Image.open(io.BytesIO(dados)) as imagem:
        largura, altura = imagem.size
        orientacao = imagem.getexif().get(_TAG_ORIENTACAO, 1)
    if orientacao in (5, 6, 7, 8):  # as quatro orientações "de lado"
        return altura, largura
    return largura, altura


def _validar_medidas(modo: str, largura, altura, lado) -> None:
    if modo not in MODOS:
        raise ValueError(f"Modo de redimensionamento desconhecido: {modo}.")
    exigidas = {
        "exato": {"a largura": largura, "a altura": altura},
        "largura": {"a largura": largura},
        "altura": {"a altura": altura},
        "lado_maior": {"o lado maior": lado},
    }[modo]
    for rotulo, valor in exigidas.items():
        if valor is None or int(valor) < 1:
            raise ValueError(f"Informe {rotulo} em pixels (pelo menos 1).")
        if int(valor) > LADO_MAXIMO:
            raise ValueError(
                f"{rotulo.capitalize()} passa do limite de {LADO_MAXIMO:,} px.".replace(",", ".")
            )


def _validar_saida(encaixe: str, formato: str) -> None:
    if encaixe not in ENCAIXES:
        raise ValueError(f"Encaixe desconhecido: {encaixe}.")
    if formato not in FORMATOS_SAIDA:
        raise ValueError(f"Formato de saída desconhecido: {formato}.")


def tamanho_redimensionado(
    original: tuple[int, int],
    *,
    modo: str = "exato",
    largura: int | None = None,
    altura: int | None = None,
    lado: int | None = None,
    nao_ampliar: bool = False,
) -> tuple[int, int]:
    """Calcula o tamanho final sem mexer em pixel nenhum.

    modo:
      exato      - largura x altura digitadas, iguais para todas as imagens
      largura    - fixa a largura; a altura acompanha a proporção de cada uma
      altura     - fixa a altura; a largura acompanha
      lado_maior - o lado mais comprido vira `lado`, seja a foto em pé ou deitada

    `nao_ampliar` só vale nos modos proporcionais: imagem menor que o pedido
    fica como está, em vez de ser esticada e sair borrada.
    """
    _validar_medidas(modo, largura, altura, lado)
    atual_l, atual_a = original
    if modo == "exato":
        return int(largura), int(altura)

    if modo == "largura":
        alvo = (int(largura), max(1, round(atual_a * int(largura) / atual_l)))
    elif modo == "altura":
        alvo = (max(1, round(atual_l * int(altura) / atual_a)), int(altura))
    else:
        fator = int(lado) / max(atual_l, atual_a)
        alvo = (max(1, round(atual_l * fator)), max(1, round(atual_a * fator)))

    if nao_ampliar and (alvo[0] > atual_l or alvo[1] > atual_a):
        return atual_l, atual_a
    return alvo


def _modo_de_trabalho(imagem: Image.Image) -> Image.Image:
    """Leva a imagem para um modo que o LANCZOS suaviza e os formatos entendem."""
    if imagem.mode in ("RGB", "RGBA", "L", "LA"):
        return imagem
    if imagem.mode in ("P", "PA"):
        # Paleta só redimensiona por "vizinho mais próximo", o que serrilha as
        # bordas. Abrindo em cores cheias o LANCZOS suaviza direito.
        tem_alfa = imagem.mode == "PA" or "transparency" in imagem.info
        return imagem.convert("RGBA" if tem_alfa else "RGB")
    if imagem.mode == "1":
        return imagem.convert("L")
    if imagem.mode.startswith("I") or imagem.mode == "F":
        # Cinza de 16 bits: um convert("L") direto estouraria tudo para branco.
        return imagem.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    return imagem.convert("RGBA" if "A" in imagem.getbands() else "RGB")


def _encaixar(
    imagem: Image.Image, alvo: tuple[int, int], cor: tuple[int, int, int], transparente: bool
) -> Image.Image:
    """Imagem inteira, centralizada, com faixas de fundo onde sobrar espaço."""
    miolo = ImageOps.contain(imagem, alvo, method=Image.LANCZOS).convert("RGBA")
    fundo = Image.new("RGBA", alvo, (*cor, 0 if transparente else 255))
    fundo.alpha_composite(
        miolo, ((alvo[0] - miolo.width) // 2, (alvo[1] - miolo.height) // 2)
    )
    return fundo if transparente else fundo.convert("RGB")


def _para_formato(imagem: Image.Image, destino: str, cor: tuple[int, int, int]) -> Image.Image:
    """JPEG não tem transparência: achata sobre a cor de fundo."""
    if destino != "JPEG":
        return imagem
    if imagem.mode in ("RGBA", "LA"):
        rgba = imagem.convert("RGBA")
        base = Image.new("RGB", imagem.size, cor)
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    if imagem.mode not in ("RGB", "L"):
        return imagem.convert("RGB")
    return imagem


def redimensionar_imagem(
    dados: bytes,
    *,
    modo: str = "exato",
    largura: int | None = None,
    altura: int | None = None,
    lado: int | None = None,
    encaixe: str = "cortar",
    fundo: str = "#FFFFFF",
    transparente: bool = False,
    formato: str = "original",
    qualidade: int = 90,
    nao_ampliar: bool = False,
) -> tuple[bytes, str, tuple[int, int]]:
    """Redimensiona uma imagem. Devolve (conteúdo, extensão, (largura, altura)).

    encaixe (só no modo exato, quando a proporção não bate com o pedido):
      cortar  - preenche o tamanho todo sem distorcer; corta o que sobra, pelo centro
      fundo   - mostra a imagem inteira sem distorcer; completa com faixas de fundo
      esticar - força o tamanho, deformando se a proporção for diferente

    formato "original" mantém PNG, JPEG e WEBP; BMP, TIFF e GIF viram PNG.
    """
    _validar_medidas(modo, largura, altura, lado)
    _validar_saida(encaixe, formato)

    with Image.open(io.BytesIO(dados)) as aberta:
        aberta.load()
        formato_original = (aberta.format or "").upper()
        perfil_cor = aberta.info.get("icc_profile")
        # Sem isso, foto de celular sai deitada e com as medidas trocadas.
        imagem = ImageOps.exif_transpose(aberta)

    if imagem.mode == "CMYK":
        perfil_cor = None  # um perfil CMYK não descreve a imagem depois de virar RGB
    imagem = _modo_de_trabalho(imagem)

    destino = formato if formato != "original" else (
        formato_original if formato_original in _EXTENSOES else "PNG"
    )
    alvo = tamanho_redimensionado(
        imagem.size, modo=modo, largura=largura, altura=altura, lado=lado,
        nao_ampliar=nao_ampliar,
    )
    if max(alvo) > LADO_MAXIMO:
        raise ValueError(
            f"ficaria com {alvo[0]} × {alvo[1]} px, acima do limite de "
            f"{LADO_MAXIMO:,} px por lado".replace(",", ".")
        )

    cor = ImageColor.getrgb(fundo)[:3]
    if alvo == imagem.size:
        resultado = imagem
    elif modo != "exato" or encaixe == "esticar":
        resultado = imagem.resize(alvo, Image.LANCZOS)
    elif encaixe == "cortar":
        resultado = ImageOps.fit(imagem, alvo, method=Image.LANCZOS, centering=(0.5, 0.5))
    else:
        resultado = _encaixar(imagem, alvo, cor, transparente and destino in _ACEITAM_ALFA)

    resultado = _para_formato(resultado, destino, cor)

    buffer = io.BytesIO()
    extras = {"icc_profile": perfil_cor} if perfil_cor else {}
    qualidade = max(1, min(int(qualidade), 100))
    if destino == "JPEG":
        resultado.save(buffer, "JPEG", quality=qualidade, optimize=True, progressive=True, **extras)
    elif destino == "WEBP":
        resultado.save(buffer, "WEBP", quality=qualidade, method=4, **extras)
    else:
        resultado.save(buffer, "PNG", **extras)
    return buffer.getvalue(), _EXTENSOES[destino], resultado.size


def redimensionar_lote(
    arquivos: list[Arquivo], *, progresso=None, **opcoes
) -> tuple[list[Arquivo], list[str]]:
    """Aplica o mesmo redimensionamento a várias imagens.

    Devolve (arquivos prontos, problemas). Uma imagem corrompida vira uma
    linha em `problemas` em vez de derrubar o lote inteiro. Opções inválidas,
    ao contrário, levantam erro antes de começar: valem para todas.
    """
    if not arquivos:
        raise ValueError("Envie pelo menos uma imagem.")
    _validar_medidas(
        opcoes.get("modo", "exato"), opcoes.get("largura"), opcoes.get("altura"), opcoes.get("lado")
    )
    _validar_saida(opcoes.get("encaixe", "cortar"), opcoes.get("formato", "original"))

    prontos: list[Arquivo] = []
    problemas: list[str] = []
    for posicao, (nome, dados) in enumerate(arquivos, start=1):
        try:
            conteudo, extensao, (largura, altura) = redimensionar_imagem(dados, **opcoes)
        except Exception as erro:
            problemas.append(f"{nome} ({erro})")
        else:
            rotulo = f"{nome_base(nome)}-{largura}x{altura}{extensao}"
            prontos.append((nome_seguro(rotulo), conteudo))
        if progresso:
            progresso(posicao / len(arquivos))
    return prontos, problemas
