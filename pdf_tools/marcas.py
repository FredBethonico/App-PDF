"""Marca d'água e numeração de páginas.

A camada extra é desenhada com o ReportLab (que sabe medir texto e embutir
fontes) e depois colada sobre o PDF original com `add_overlay` do pikepdf.

Todas as camadas de um trabalho vão para um único PDF temporário, com uma
página por página alvo. Isso evita abrir centenas de documentos em memória
num arquivo grande e mantém o conteúdo original intacto por baixo.
"""

from __future__ import annotations

import io

import pikepdf
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .documento import abrir, salvar
from .ranges import parse_intervalo

FONTES = ["Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier"]

POSICOES = [
    "Centro",
    "Rodapé centro",
    "Rodapé direita",
    "Rodapé esquerda",
    "Cabeçalho centro",
    "Cabeçalho direita",
    "Cabeçalho esquerda",
    "Alternado (livro)",
]

# Fração da largura/altura usada como margem nas posições de canto.
_MARGEM_PADRAO_PT = 28.0


def _caixa(pagina: pikepdf.Page) -> pikepdf.Rectangle:
    """Área visível da página. O TrimBox é o que a gráfica considera papel."""
    for chave in ("/TrimBox", "/CropBox", "/MediaBox"):
        valor = pagina.obj.get(chave)
        if valor is not None:
            try:
                return pikepdf.Rectangle(valor)
            except Exception:
                continue
    return pikepdf.Rectangle(pagina.mediabox)


def _ancorar(
    posicao: str,
    largura: float,
    altura: float,
    margem: float,
    numero_da_pagina: int,
) -> tuple[float, float, str]:
    """Devolve (x, y, alinhamento) para a posição escolhida."""
    if posicao == "Alternado (livro)":
        # Páginas ímpares ficam à direita do livro aberto, pares à esquerda.
        posicao = "Rodapé direita" if numero_da_pagina % 2 else "Rodapé esquerda"

    no_rodape = posicao.startswith("Rodapé")
    y = margem if no_rodape else altura - margem
    if posicao == "Centro":
        return largura / 2, altura / 2, "centro"
    if posicao.endswith("centro"):
        return largura / 2, y, "centro"
    if posicao.endswith("direita"):
        return largura - margem, y, "direita"
    return margem, y, "esquerda"


def _escrever(c: canvas.Canvas, x: float, y: float, texto: str, alinhamento: str) -> None:
    if alinhamento == "centro":
        c.drawCentredString(x, y, texto)
    elif alinhamento == "direita":
        c.drawRightString(x, y, texto)
    else:
        c.drawString(x, y, texto)


def _aplicar_camadas(
    dados: bytes,
    alvos: list[int],
    desenhar,
    *,
    atras: bool,
    senha: str,
) -> bytes:
    """Motor comum: cria uma sobreposição por página alvo e cola no original.

    `desenhar(c, indice_da_pagina, largura, altura)` recebe um canvas já do
    tamanho certo e desenha o que quiser nele.
    """
    with abrir(dados, senha) as pdf:
        if not alvos:
            raise ValueError("Nenhuma página selecionada.")

        caixas = [_caixa(pdf.pages[i]) for i in alvos]

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer)
        for indice, caixa in zip(alvos, caixas):
            c.setPageSize((caixa.width, caixa.height))
            desenhar(c, indice, caixa.width, caixa.height)
            c.showPage()
        c.save()

        with pikepdf.open(io.BytesIO(buffer.getvalue())) as camadas:
            for posicao, (indice, caixa) in enumerate(zip(alvos, caixas)):
                pagina = pdf.pages[indice]
                camada = camadas.pages[posicao]
                if atras:
                    pagina.add_underlay(camada, caixa)
                else:
                    pagina.add_overlay(camada, caixa)
            return salvar(pdf, compress_streams=True)


def marca_dagua_texto(
    dados: bytes,
    texto: str,
    *,
    fonte: str = "Helvetica-Bold",
    tamanho: int = 60,
    cor: str = "#FF0000",
    opacidade: float = 0.15,
    angulo: float = 45,
    mosaico: bool = False,
    posicao: str = "Centro",
    intervalo: str = "",
    atras: bool = False,
    senha: str = "",
) -> bytes:
    """Carimba um texto em todas (ou algumas) páginas."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Digite o texto da marca d'água.")

    tinta = HexColor(cor)

    def desenhar(c: canvas.Canvas, indice: int, largura: float, altura: float) -> None:
        c.saveState()
        c.setFont(fonte, tamanho)
        c.setFillColor(tinta)
        c.setFillAlpha(opacidade)
        c.setStrokeAlpha(opacidade)

        if mosaico:
            largura_texto = c.stringWidth(texto, fonte, tamanho)
            passo_x = max(largura_texto * 1.6, tamanho * 4)
            passo_y = max(tamanho * 4.0, 60)
            # Sobra nas bordas para o texto girado não sumir nos cantos.
            y = -altura * 0.2
            linha = 0
            while y < altura * 1.2:
                deslocamento = (passo_x / 2) if linha % 2 else 0
                x = -largura * 0.2 + deslocamento
                while x < largura * 1.2:
                    c.saveState()
                    c.translate(x, y)
                    c.rotate(angulo)
                    c.drawCentredString(0, 0, texto)
                    c.restoreState()
                    x += passo_x
                y += passo_y
                linha += 1
        else:
            x, y, alinhamento = _ancorar(
                posicao, largura, altura, _MARGEM_PADRAO_PT, indice + 1
            )
            c.saveState()
            c.translate(x, y)
            c.rotate(angulo)
            _escrever(c, 0, 0, texto, alinhamento)
            c.restoreState()

        c.restoreState()

    with abrir(dados, senha) as pdf:
        alvos = sorted(set(parse_intervalo(intervalo, len(pdf.pages))))
    return _aplicar_camadas(dados, alvos, desenhar, atras=atras, senha=senha)


def marca_dagua_imagem(
    dados: bytes,
    imagem: bytes,
    *,
    largura_relativa: float = 0.4,
    opacidade: float = 0.2,
    posicao: str = "Centro",
    angulo: float = 0,
    intervalo: str = "",
    atras: bool = True,
    senha: str = "",
) -> bytes:
    """Carimba uma imagem (logo, assinatura) nas páginas escolhidas.

    `largura_relativa` é a fração da largura da página que a imagem ocupa;
    a altura acompanha para não distorcer.
    """
    leitor = ImageReader(io.BytesIO(imagem))
    img_largura, img_altura = leitor.getSize()
    if not img_largura or not img_altura:
        raise ValueError("Não consegui ler as dimensões da imagem.")
    proporcao = img_altura / img_largura

    def desenhar(c: canvas.Canvas, indice: int, largura: float, altura: float) -> None:
        alvo_largura = largura * largura_relativa
        alvo_altura = alvo_largura * proporcao
        x, y, alinhamento = _ancorar(
            posicao, largura, altura, _MARGEM_PADRAO_PT, indice + 1
        )
        if alinhamento == "centro":
            canto_x = x - alvo_largura / 2
        elif alinhamento == "direita":
            canto_x = x - alvo_largura
        else:
            canto_x = x
        canto_y = y if posicao.startswith("Rodapé") else y - alvo_altura
        if posicao == "Centro":
            canto_y = y - alvo_altura / 2

        c.saveState()
        c.setFillAlpha(opacidade)
        c.setStrokeAlpha(opacidade)
        if angulo:
            centro_x = canto_x + alvo_largura / 2
            centro_y = canto_y + alvo_altura / 2
            c.translate(centro_x, centro_y)
            c.rotate(angulo)
            c.translate(-centro_x, -centro_y)
        c.drawImage(
            leitor,
            canto_x,
            canto_y,
            width=alvo_largura,
            height=alvo_altura,
            mask="auto",
            preserveAspectRatio=True,
        )
        c.restoreState()

    with abrir(dados, senha) as pdf:
        alvos = sorted(set(parse_intervalo(intervalo, len(pdf.pages))))
    return _aplicar_camadas(dados, alvos, desenhar, atras=atras, senha=senha)


def numerar_paginas(
    dados: bytes,
    *,
    formato: str = "{n}",
    posicao: str = "Rodapé centro",
    fonte: str = "Helvetica",
    tamanho: int = 10,
    cor: str = "#333333",
    margem_mm: float = 12.0,
    primeiro_numero: int = 1,
    comecar_na_pagina: int = 1,
    senha: str = "",
) -> bytes:
    """Escreve o número em cada página.

    `formato` aceita {n} (número da página) e {total} (quantas serão numeradas),
    então "Página {n} de {total}" funciona.

    `comecar_na_pagina` pula capa e folha de rosto: as páginas anteriores ficam
    sem número, e a contagem começa em `primeiro_numero` na primeira numerada.
    """
    if "{n}" not in formato and "{total}" not in formato:
        raise ValueError("O formato precisa conter {n}, por exemplo: Página {n}.")

    tinta = HexColor(cor)
    margem = margem_mm / 25.4 * 72

    with abrir(dados, senha) as pdf:
        total_paginas = len(pdf.pages)

    if not 1 <= comecar_na_pagina <= total_paginas:
        raise ValueError(
            f"A página inicial precisa estar entre 1 e {total_paginas}."
        )

    alvos = list(range(comecar_na_pagina - 1, total_paginas))
    ultimo_numero = primeiro_numero + len(alvos) - 1
    numeros = {
        indice: primeiro_numero + ordem for ordem, indice in enumerate(alvos)
    }

    def desenhar(c: canvas.Canvas, indice: int, largura: float, altura: float) -> None:
        numero = numeros[indice]
        try:
            texto = formato.format(n=numero, total=ultimo_numero)
        except (KeyError, IndexError):
            texto = str(numero)
        # O alternado usa a paridade do número impresso, não a da posição.
        x, y, alinhamento = _ancorar(posicao, largura, altura, margem, numero)
        c.saveState()
        c.setFont(fonte, tamanho)
        c.setFillColor(tinta)
        if not posicao.startswith("Rodapé") and posicao != "Centro":
            y -= tamanho  # cabeçalho: desce a linha de base para dentro da página
        _escrever(c, x, y, texto, alinhamento)
        c.restoreState()

    return _aplicar_camadas(dados, alvos, desenhar, atras=False, senha=senha)
