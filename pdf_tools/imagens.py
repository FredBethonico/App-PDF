"""Conversao entre PDF e imagens, e renderizacao de previas.

Usa pypdfium2 (motor do Chrome) no lugar do pdf2image/poppler: e um wheel
puro, sem binario externo para instalar, o que faz o app rodar igual no
Windows e no Streamlit Cloud.
"""

from __future__ import annotations

import io

import img2pdf
import pypdfium2 as pdfium
from PIL import Image

from .documento import PdfInvalido, PdfProtegido
from .ranges import parse_intervalo
from .util import Arquivo, nome_base, nome_seguro, numerar

# Paginas de revista em alta resolucao passam do limite anti-"bomba" do Pillow.
# Aqui a origem e sempre um arquivo que o proprio usuario enviou, entao o
# limite so atrapalha; o teto real de memoria vem de MAX_PIXELS_POR_PAGINA.
Image.MAX_IMAGE_PIXELS = None

MAX_PIXELS_POR_PAGINA = 80_000_000  # ~8000 x 10000 px
FORMATOS_ENTRADA = ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"]

_PAGINAS_PT = {
    "A4 retrato": (595.28, 841.89),
    "A4 paisagem": (841.89, 595.28),
    "Carta retrato": (612.0, 792.0),
    "Carta paisagem": (792.0, 612.0),
    "A3 retrato": (841.89, 1190.55),
    "A5 retrato": (419.53, 595.28),
}
TAMANHOS_PAGINA = ["Do tamanho da imagem", *_PAGINAS_PT]


def _documento(dados: bytes, senha: str = "") -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(dados, password=senha or None)
    except pdfium.PdfiumError as erro:
        texto = str(erro).lower()
        if "password" in texto:
            raise PdfProtegido("Este PDF precisa de senha para ser aberto.") from None
        raise PdfInvalido(f"Nao consegui abrir o PDF ({erro}).") from None


def contar_paginas(dados: bytes, senha: str = "") -> int:
    doc = _documento(dados, senha)
    try:
        return len(doc)
    finally:
        doc.close()


def _escala_segura(pagina: pdfium.PdfPage, dpi: int) -> float:
    """Reduz o DPI se a pagina for grande demais para caber na memoria."""
    escala = dpi / 72
    largura, altura = pagina.get_size()
    pixels = (largura * escala) * (altura * escala)
    if pixels > MAX_PIXELS_POR_PAGINA:
        escala *= (MAX_PIXELS_POR_PAGINA / pixels) ** 0.5
    return max(escala, 0.05)


def renderizar_pagina(
    dados: bytes, indice: int, dpi: int = 150, senha: str = ""
) -> Image.Image:
    """Renderiza uma pagina como imagem PIL (RGB)."""
    doc = _documento(dados, senha)
    try:
        pagina = doc[indice]
        imagem = pagina.render(scale=_escala_segura(pagina, dpi)).to_pil()
        return imagem.convert("RGB")
    finally:
        doc.close()


def miniaturas(
    dados: bytes, indices: list[int] | None = None, largura: int = 220, senha: str = ""
) -> list[Image.Image]:
    """Previas pequenas para a grade de organizacao de paginas."""
    doc = _documento(dados, senha)
    try:
        alvos = range(len(doc)) if indices is None else indices
        saida = []
        for i in alvos:
            pagina = doc[i]
            escala = largura / max(pagina.get_width(), 1)
            saida.append(pagina.render(scale=escala).to_pil().convert("RGB"))
        return saida
    finally:
        doc.close()


def pdf_para_imagens(
    dados: bytes,
    *,
    dpi: int = 200,
    formato: str = "PNG",
    qualidade: int = 90,
    intervalo: str = "",
    nome: str = "documento",
    senha: str = "",
    progresso=None,
) -> list[Arquivo]:
    """Converte paginas em arquivos de imagem individuais."""
    formato = formato.upper()
    if formato not in {"PNG", "JPEG", "WEBP"}:
        raise ValueError(f"Formato de saída não suportado: {formato}.")
    extensao = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[formato]

    doc = _documento(dados, senha)
    try:
        total = len(doc)
        indices = parse_intervalo(intervalo, total)
        base = nome_base(nome)
        saida: list[Arquivo] = []
        for posicao, indice in enumerate(indices, start=1):
            pagina = doc[indice]
            imagem = pagina.render(scale=_escala_segura(pagina, dpi)).to_pil()
            buffer = io.BytesIO()
            if formato == "PNG":
                imagem.convert("RGB").save(buffer, "PNG", optimize=True)
            elif formato == "JPEG":
                imagem.convert("RGB").save(
                    buffer, "JPEG", quality=qualidade, optimize=True, progressive=True
                )
            else:
                imagem.convert("RGB").save(buffer, "WEBP", quality=qualidade)
            rotulo = f"{base}-pagina-{numerar(indice + 1, total)}{extensao}"
            saida.append((nome_seguro(rotulo), buffer.getvalue()))
            if progresso:
                progresso(posicao / len(indices))
        return saida
    finally:
        doc.close()


def _normalizar_para_pdf(dados: bytes, qualidade_jpeg: int | None) -> bytes:
    """Prepara uma imagem para o img2pdf.

    O img2pdf recusa canal alfa (PDF nao tem transparencia de pagina) e nao
    conhece todos os modos do Pillow. JPEG e PNG "limpos" passam direto, sem
    reencodar - e o que mantem a conversao sem perda.
    """
    with Image.open(io.BytesIO(dados)) as imagem:
        imagem.load()
        formato = (imagem.format or "").upper()
        tem_alfa = imagem.mode in {"RGBA", "LA", "PA"} or "transparency" in imagem.info
        animada = getattr(imagem, "n_frames", 1) > 1

        if formato == "JPEG" and not tem_alfa and qualidade_jpeg is None:
            return dados  # ja e o formato nativo do PDF: copia direta
        if formato == "PNG" and not tem_alfa and qualidade_jpeg is None and not animada:
            return dados

        plano = imagem.convert("RGBA") if tem_alfa else imagem.convert("RGB")
        if tem_alfa:
            fundo = Image.new("RGBA", plano.size, (255, 255, 255, 255))
            plano = Image.alpha_composite(fundo, plano).convert("RGB")
        else:
            plano = plano.convert("RGB")

        buffer = io.BytesIO()
        if qualidade_jpeg is None:
            plano.save(buffer, "PNG", optimize=True)
        else:
            plano.save(buffer, "JPEG", quality=qualidade_jpeg, optimize=True)
        return buffer.getvalue()


def imagens_para_pdf(
    arquivos: list[Arquivo],
    *,
    tamanho_pagina: str = "Do tamanho da imagem",
    margem_mm: float = 0.0,
    recomprimir_jpeg: int | None = None,
) -> bytes:
    """Junta imagens em um unico PDF, uma por pagina, na ordem recebida."""
    if not arquivos:
        raise ValueError("Envie pelo menos uma imagem.")

    preparadas = []
    problemas = []
    for nome, dados in arquivos:
        try:
            preparadas.append(_normalizar_para_pdf(dados, recomprimir_jpeg))
        except Exception as erro:
            problemas.append(f"{nome} ({erro})")
    if problemas:
        raise ValueError("Não consegui ler: " + "; ".join(problemas))

    if tamanho_pagina == "Do tamanho da imagem":
        layout = img2pdf.get_layout_fun()
        if margem_mm:
            # Sem pagina fixa, a margem vira uma folga em volta da imagem.
            borda = img2pdf.mm_to_pt(margem_mm)
            layout = img2pdf.get_layout_fun(border=(borda, borda))
    else:
        pagina = _PAGINAS_PT[tamanho_pagina]
        borda = img2pdf.mm_to_pt(margem_mm) if margem_mm else None
        layout = img2pdf.get_layout_fun(
            pagesize=pagina,
            border=(borda, borda) if borda else None,
            fit=img2pdf.FitMode.into,
            auto_orient=True,
        )

    return img2pdf.convert(preparadas, layout_fun=layout)
