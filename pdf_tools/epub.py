"""Conversão de livros digitais EPUB para PDF.

Usa o PyMuPDF (motor MuPDF), que lê o EPUB, aplica o CSS do livro, faz a
paginação no tamanho de página pedido e grava o PDF — tudo na memória e sem
binário externo (o wheel já traz o MuPDF compilado).

O que sai no PDF:
  - texto de verdade (selecionável e pesquisável), com as fontes do livro;
  - imagens do livro;
  - sumário do EPUB como marcadores (o painel lateral do leitor de PDF);
  - links internos (notas, índice remissivo) e externos clicáveis;
  - título e autor nos metadados.

O que não dá para converter: livros com DRM (Kindle, Adobe, Apple). A
proteção cifra o conteúdo; sem a chave da loja não há o que ler.
"""

from __future__ import annotations

import io
import re
import threading
import zipfile
from dataclasses import dataclass, field

import pymupdf

from .util import Arquivo, nome_base, nome_seguro

# --------------------------------------------------------------------------
# Opções
# --------------------------------------------------------------------------

# Tamanhos em pontos (1 pt = 1/72 pol). A5 e 6x9 são os formatos de livro
# mais comuns; "Leitor digital" imita a tela de 6" de um Kindle/Kobo.
TAMANHOS_PAGINA_EPUB: dict[str, tuple[float, float]] = {
    "A5 (livro)": (419.53, 595.28),
    "A4": (595.28, 841.89),
    "A6 (bolso)": (297.64, 419.53),
    "6 x 9 pol (brochura)": (432.0, 648.0),
    "Carta": (612.0, 792.0),
    "Leitor digital (6 pol)": (255.12, 340.16),  # 90 x 120 mm
}
TAMANHO_PADRAO = "A5 (livro)"

# None = mantém a fonte que o livro escolheu.
FONTES_EPUB: dict[str, str | None] = {
    "Do livro": None,
    "Serifada": "serif",
    "Sem serifa": "sans-serif",
    "Monoespaçada": "monospace",
}

ENTRELINHAS: dict[str, float | None] = {
    "Do livro": None,
    "Apertada (1,2)": 1.2,
    "Normal (1,4)": 1.4,
    "Folgada (1,6)": 1.6,
    "Dupla (2,0)": 2.0,
}

FONTE_MINIMA, FONTE_MAXIMA = 6.0, 32.0
MARGEM_MAXIMA_MM = 50.0

# Limites contra arquivo malicioso ou gigante: um EPUB é um zip, e zip
# pequeno pode descompactar em gigabytes ("zip bomb").
LIMITE_EPUB = 300 * 1024 * 1024  # bytes do arquivo enviado
LIMITE_DESCOMPACTADO = 1500 * 1024 * 1024
MAX_PAGINAS = 15_000

# Cifras de *ofuscação de fonte* aparecem em EPUBs comuns, sem DRM: só
# embaralham os primeiros bytes da fonte, e o MuPDF sabe desfazer.
_OFUSCACAO_DE_FONTE = {
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
}

# O MuPDF tem estado global (o liga/desliga do CSS do livro e as mensagens
# de aviso). Com várias abas do Streamlit convertendo ao mesmo tempo, uma
# conversão por vez evita que uma mexa na configuração da outra.
_TRAVA = threading.Lock()

_PAGINAS_POR_BLOCO = 25  # de quantas em quantas páginas o progresso anda


class EpubInvalido(ValueError):
    """O arquivo não é um EPUB legível."""


class EpubProtegido(EpubInvalido):
    """O EPUB tem DRM: o conteúdo está cifrado pela loja."""


def _etapa(mostrar: bool, texto: str) -> None:
    """Avisa no terminal (log do servidor) em que passo a conversão está."""
    if mostrar:
        print(f"[epub→pdf] {texto}", flush=True)


# --------------------------------------------------------------------------
# Validação do arquivo
# --------------------------------------------------------------------------


@dataclass
class InfoEpub:
    titulo: str
    autor: str
    capitulos: int
    imagens: int
    tamanho: int
    idioma: str = ""
    editora: str = ""
    avisos: list[str] = field(default_factory=list)


def _verificar_zip(dados: bytes) -> list[str]:
    """Confere a estrutura do EPUB antes de entregar ao MuPDF.

    Levanta erro para o que impede a conversão e devolve avisos para o que é
    só desleixo de quem gerou o arquivo (e o MuPDF tolera).
    """
    if not dados:
        raise EpubInvalido("O arquivo chegou vazio.")
    if len(dados) > LIMITE_EPUB:
        raise EpubInvalido(
            f"O arquivo passa do limite de {LIMITE_EPUB // (1024 * 1024)} MB."
        )
    if dados[:4] != b"PK\x03\x04":
        if dados[:8] == b"BOOKMOBI" or dados[60:68] == b"BOOKMOBI":
            raise EpubInvalido(
                "Este arquivo é um MOBI/AZW (formato do Kindle), não um EPUB."
            )
        if dados[:5] == b"%PDF-":
            raise EpubInvalido("Este arquivo já é um PDF.")
        raise EpubInvalido("Este arquivo não é um EPUB (um EPUB é um pacote zip).")

    try:
        pacote = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        raise EpubInvalido("O EPUB está corrompido (o pacote zip não abre).") from None

    avisos: list[str] = []
    with pacote:
        nomes = set(pacote.namelist())
        if sum(item.file_size for item in pacote.infolist()) > LIMITE_DESCOMPACTADO:
            raise EpubInvalido("O EPUB descompactado fica grande demais para converter.")
        if "META-INF/container.xml" not in nomes:
            raise EpubInvalido(
                "O EPUB está incompleto: falta o META-INF/container.xml, "
                "que diz onde o livro começa."
            )
        if "META-INF/rights.xml" in nomes or "META-INF/sinf.xml" in nomes:
            raise EpubProtegido(_MENSAGEM_DRM)
        if "META-INF/encryption.xml" in nomes:
            texto = pacote.read("META-INF/encryption.xml").decode("utf-8", "replace")
            algoritmos = set(re.findall(r'Algorithm\s*=\s*["\']([^"\']+)', texto))
            # Só método de cifra conta: os de digest/chave também têm Algorithm.
            metodos = set(
                re.findall(r'EncryptionMethod[^>]*Algorithm\s*=\s*["\']([^"\']+)', texto)
            )
            if metodos - _OFUSCACAO_DE_FONTE or (not metodos and algoritmos):
                raise EpubProtegido(_MENSAGEM_DRM)
        if "mimetype" not in nomes:
            avisos.append("o arquivo não declara o tipo (mimetype); converti mesmo assim")
    return avisos


_MENSAGEM_DRM = (
    "Este livro tem DRM (proteção da loja que o vendeu): o conteúdo está "
    "cifrado e não dá para converter. Livros sem DRM — de domínio público, "
    "de editoras que vendem sem proteção ou gerados por você — funcionam."
)


def _abrir(dados: bytes) -> pymupdf.Document:
    try:
        documento = pymupdf.open(stream=dados, filetype="epub")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as erro:
        raise EpubInvalido(f"Não consegui ler este EPUB ({erro}).") from None
    if documento.needs_pass:
        documento.close()
        raise EpubProtegido(_MENSAGEM_DRM)
    return documento


def _texto(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def _metadado_opf(dados: bytes, campo: str) -> str:
    """Lê um <dc:campo> do OPF direto (o MuPDF só expõe título e autor)."""
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as pacote:
            container = pacote.read("META-INF/container.xml").decode("utf-8", "replace")
            caminho = re.search(r'full-path\s*=\s*["\']([^"\']+)', container)
            if not caminho:
                return ""
            opf = pacote.read(caminho.group(1)).decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        return ""
    achado = re.search(rf"<dc:{campo}\b[^>]*>(.*?)</dc:{campo}>", opf, re.S | re.I)
    return _texto(re.sub(r"<[^>]+>", "", achado.group(1))) if achado else ""


def _contar_imagens(dados: bytes) -> int:
    with zipfile.ZipFile(io.BytesIO(dados)) as pacote:
        return sum(
            1
            for nome in pacote.namelist()
            if nome.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "gif", "svg", "webp"}
        )


def inspecionar_epub(dados: bytes) -> InfoEpub:
    """Título, autor e tamanho do livro, sem paginar nada (é rápido)."""
    avisos = _verificar_zip(dados)
    with _TRAVA:
        documento = _abrir(dados)
        try:
            meta = documento.metadata or {}
            capitulos = documento.chapter_count
        finally:
            documento.close()
    return InfoEpub(
        titulo=_texto(meta.get("title")),
        autor=_texto(meta.get("author")),
        capitulos=capitulos,
        imagens=_contar_imagens(dados),
        tamanho=len(dados),
        idioma=_metadado_opf(dados, "language"),
        editora=_metadado_opf(dados, "publisher"),
        avisos=avisos,
    )


# --------------------------------------------------------------------------
# Conversão
# --------------------------------------------------------------------------


def _validar_opcoes(
    tamanho_pagina: str,
    margem_mm: float,
    tamanho_fonte: float,
    fonte: str,
    entrelinha: str,
) -> None:
    if tamanho_pagina not in TAMANHOS_PAGINA_EPUB:
        raise ValueError(f"Tamanho de página desconhecido: {tamanho_pagina}.")
    if fonte not in FONTES_EPUB:
        raise ValueError(f"Fonte desconhecida: {fonte}.")
    if entrelinha not in ENTRELINHAS:
        raise ValueError(f"Entrelinha desconhecida: {entrelinha}.")
    if not FONTE_MINIMA <= tamanho_fonte <= FONTE_MAXIMA:
        raise ValueError(
            f"O tamanho da letra precisa ficar entre {FONTE_MINIMA:g} e {FONTE_MAXIMA:g} pt."
        )
    if not 0 <= margem_mm <= MARGEM_MAXIMA_MM:
        raise ValueError(f"A margem precisa ficar entre 0 e {MARGEM_MAXIMA_MM:g} mm.")
    largura, altura = TAMANHOS_PAGINA_EPUB[tamanho_pagina]
    sobra = min(largura, altura) - 2 * margem_mm / 25.4 * 72
    if sobra < 4 * tamanho_fonte:
        raise ValueError(
            "Com essa margem não sobra espaço para o texto nesta página. "
            "Diminua a margem ou escolha uma página maior."
        )


def _css(
    margem_mm: float,
    fonte: str,
    entrelinha: str,
    justificar: bool,
) -> str:
    """CSS aplicado por cima do livro.

    `!important` é o que garante vencer o CSS do próprio EPUB, que costuma
    fixar fonte e entrelinha em cada parágrafo.
    """
    regras = [
        f"@page {{ margin: {margem_mm:g}mm; }}",
        # O MuPDF põe 1em de margem no <body>; somaria com a margem da página.
        "body { margin: 0 !important; padding: 0 !important; }",
        # Imagem maior que a página seria cortada; aqui ela encolhe para caber.
        "img, svg { max-width: 100% !important; max-height: 100% !important; }",
    ]
    familia = FONTES_EPUB[fonte]
    if familia:
        regras.append(
            f"body, p, div, span, li, td, th, blockquote, h1, h2, h3, h4, h5, h6 "
            f"{{ font-family: {familia} !important; }}"
        )
    altura = ENTRELINHAS[entrelinha]
    if altura:
        regras.append(f"body, p, div, li, blockquote {{ line-height: {altura:g} !important; }}")
    if justificar:
        regras.append("p { text-align: justify !important; }")
    return "\n".join(regras)


def _sumario_valido(sumario: list, total: int) -> list[list]:
    """Ajusta o sumário do EPUB ao que o PDF aceita.

    O `set_toc` recusa saltos de nível (1 -> 3) e páginas fora do arquivo,
    coisa comum em sumários de EPUB feitos à mão.
    """
    ajustado: list[list] = []
    nivel_anterior = 0
    for item in sumario:
        nivel, titulo, pagina = int(item[0]), _texto(item[1]), int(item[2])
        if not titulo:
            continue
        nivel = max(1, min(nivel, nivel_anterior + 1))
        pagina = min(max(pagina, 1), total) if pagina > 0 else -1
        ajustado.append([nivel, titulo[:250], pagina])
        nivel_anterior = nivel
    return ajustado


def _copiar_links(origem: pymupdf.Document, pdf: pymupdf.Document) -> int:
    """Recria os links do livro no PDF.

    O `convert_to_pdf` do MuPDF até copia os links, mas os internos saem
    apontando para a página errada (conta a partir do começo do capítulo,
    não do livro). Aqui eles são apagados e refeitos com o destino certo.
    """
    total = pdf.page_count
    criados = 0
    for indice in range(total):
        pagina_pdf = pdf[indice]
        for link in pagina_pdf.get_links():
            pagina_pdf.delete_link(link)
        for link in origem[indice].get_links():
            tipo = link.get("kind")
            if tipo == pymupdf.LINK_URI and link.get("uri"):
                pagina_pdf.insert_link({"kind": tipo, "from": link["from"], "uri": link["uri"]})
                criados += 1
            elif tipo == pymupdf.LINK_GOTO and 0 <= link.get("page", -1) < total:
                pagina_pdf.insert_link(
                    {
                        "kind": tipo,
                        "from": link["from"],
                        "page": link["page"],
                        "to": link.get("to", pymupdf.Point(0, 0)),
                        "zoom": 0,
                    }
                )
                criados += 1
    return criados


def _desenhar_paginas(
    origem: pymupdf.Document, total: int, progresso, avisar
) -> pymupdf.Document:
    """Desenha cada página paginada do EPUB numa página de PDF.

    Faz à mão o que o `Document.convert_to_pdf` faz, por dois motivos: ele
    quebra quando recebe um intervalo que não começa na página 0 (então não
    dá para converter em blocos e mostrar progresso), e erra o destino dos
    links internos (usa a página dentro do capítulo, não no livro). Os links
    são refeitos depois, em `_copiar_links`.
    """
    mupdf = pymupdf.mupdf
    saida = mupdf.PdfDocument()
    for indice in range(total):
        if indice % _PAGINAS_POR_BLOCO == 0:
            avisar(f"desenhando páginas {indice + 1}–"
                   f"{min(indice + _PAGINAS_POR_BLOCO, total)} de {total}")
            if progresso:
                progresso(0.85 * indice / total)
        pagina = mupdf.fz_load_page(origem.this, indice)
        caixa = mupdf.fz_bound_page(pagina)
        dispositivo, recursos, conteudo = mupdf.pdf_page_write(saida, caixa)
        mupdf.fz_run_page(pagina, dispositivo, mupdf.FzMatrix(), mupdf.FzCookie())
        mupdf.fz_close_device(dispositivo)
        objeto = mupdf.pdf_add_page(saida, caixa, 0, recursos, conteudo)
        mupdf.pdf_insert_page(saida, -1, objeto)
    if progresso:
        progresso(0.85)

    opcoes = mupdf.PdfWriteOptions()
    opcoes.do_compress = 1
    buffer = mupdf.fz_new_buffer(1 << 16)
    destino = mupdf.FzOutput(buffer)
    mupdf.pdf_write_document(saida, destino, opcoes)
    destino.fz_close_output()
    return pymupdf.open("pdf", mupdf.fz_buffer_extract_copy(buffer))


def _restaurar_padrao() -> None:
    """Devolve o MuPDF ao estado de fábrica para a próxima conversão."""
    pymupdf.mupdf.fz_set_user_css("")
    pymupdf.mupdf.fz_set_use_document_css(1)


@dataclass
class ResultadoEpub:
    pdf: bytes
    paginas: int
    marcadores: int
    links: int
    titulo: str
    avisos: list[str] = field(default_factory=list)


def epub_para_pdf(
    dados: bytes,
    *,
    tamanho_pagina: str = TAMANHO_PADRAO,
    margem_mm: float = 15,
    tamanho_fonte: float = 11,
    fonte: str = "Do livro",
    entrelinha: str = "Do livro",
    justificar: bool = False,
    estilo_do_livro: bool = True,
    sumario: bool = True,
    links: bool = True,
    progresso=None,
    mostrar_etapas: bool = True,
) -> ResultadoEpub:
    """Converte um EPUB em PDF paginado.

    - `tamanho_pagina`: chave de TAMANHOS_PAGINA_EPUB.
    - `margem_mm`: margem igual nos quatro lados.
    - `tamanho_fonte`: corpo do texto em pt; o livro usa proporções disso
      (títulos em 2em continuam o dobro).
    - `fonte` / `entrelinha`: chaves de FONTES_EPUB / ENTRELINHAS; "Do livro"
      respeita o que o EPUB definiu.
    - `estilo_do_livro=False` ignora o CSS do EPUB (útil quando o livro tem
      estilo quebrado: letra minúscula, cor ilegível, margens enormes).
    - `sumario` / `links`: marcadores e links clicáveis no PDF.
    - `progresso`: função que recebe uma fração de 0 a 1.
    - `mostrar_etapas`: imprime no terminal o passo atual.
    """
    _validar_opcoes(tamanho_pagina, margem_mm, tamanho_fonte, fonte, entrelinha)
    avisar = lambda texto: _etapa(mostrar_etapas, texto)  # noqa: E731

    avisar("conferindo a estrutura do EPUB")
    avisos = _verificar_zip(dados)
    largura, altura = TAMANHOS_PAGINA_EPUB[tamanho_pagina]

    with _TRAVA:
        pymupdf.TOOLS.mupdf_display_errors(False)  # avisos do MuPDF poluem o log
        # CSS "de usuário" global, e não Document.apply_css: este último
        # religa o CSS do livro por baixo dos panos, e aí estilo_do_livro=False
        # não teria efeito. Por ser global, só mexe nele com a trava na mão.
        pymupdf.mupdf.fz_set_use_document_css(1 if estilo_do_livro else 0)
        pymupdf.mupdf.fz_set_user_css(_css(margem_mm, fonte, entrelinha, justificar))
        try:
            origem = _abrir(dados)
        except BaseException:
            _restaurar_padrao()
            raise
        try:
            avisar(f"paginando em {tamanho_pagina}, letra {tamanho_fonte:g} pt")
            origem.layout(width=largura, height=altura, fontsize=tamanho_fonte)
            total = origem.page_count
            if total == 0:
                raise EpubInvalido("O EPUB não tem nenhuma página de conteúdo.")
            if total > MAX_PAGINAS:
                raise EpubInvalido(
                    f"O livro daria {total} páginas, acima do limite de {MAX_PAGINAS}. "
                    "Escolha uma página maior ou uma letra menor."
                )
            avisar(f"{total} página(s) a gerar")

            pdf = _desenhar_paginas(origem, total, progresso, avisar)
            try:
                quantos_links = 0
                if links:
                    avisar("refazendo os links internos e externos")
                    quantos_links = _copiar_links(origem, pdf)

                marcadores: list[list] = []
                if sumario:
                    avisar("montando os marcadores a partir do sumário")
                    marcadores = _sumario_valido(origem.get_toc(simple=True), total)
                    if not marcadores:
                        avisos.append("o livro não tem sumário, então o PDF saiu sem marcadores")
                    else:
                        try:
                            pdf.set_toc(marcadores)
                        except ValueError:
                            marcadores = []
                            avisos.append("o sumário do livro estava mal formado e ficou de fora")

                meta = origem.metadata or {}
                titulo = _texto(meta.get("title"))
                pdf.set_metadata(
                    {
                        "title": titulo,
                        "author": _texto(meta.get("author")),
                        "subject": _metadado_opf(dados, "description")[:500],
                        "creator": "Ferramentas de PDF (EPUB para PDF)",
                        "producer": f"PyMuPDF {pymupdf.VersionBind}",
                    }
                )
                if progresso:
                    progresso(0.9)

                avisar("enxugando as fontes e gravando o PDF")
                try:
                    pdf.subset_fonts()  # embute só as letras usadas: corta muito o tamanho
                except Exception:  # noqa: BLE001 - otimização; sem ela o PDF vale igual
                    avisos.append("não consegui enxugar as fontes; o PDF ficou maior que o normal")
                saida = pdf.tobytes(garbage=3, deflate=True, deflate_fonts=True)
            finally:
                pdf.close()
        finally:
            origem.close()
            _restaurar_padrao()

    if progresso:
        progresso(1.0)
    avisar(f"pronto: {total} página(s), {len(saida) / 1024:.0f} KB")
    return ResultadoEpub(
        pdf=saida,
        paginas=total,
        marcadores=len(marcadores),
        links=quantos_links,
        titulo=titulo,
        avisos=avisos,
    )


def converter_epubs_lote(
    arquivos: list[Arquivo], *, progresso=None, mostrar_etapas: bool = True, **opcoes
) -> tuple[list[Arquivo], list[str], list[str]]:
    """Converte vários EPUBs com as mesmas opções.

    Devolve (prontos, problemas, avisos). Um livro ruim (DRM, corrompido)
    vira uma linha em `problemas` em vez de derrubar o lote; `avisos` são
    ressalvas de livros que converteram (ex.: sem sumário). Opções
    inválidas levantam erro antes de começar, porque valem para todos.
    """
    if not arquivos:
        raise ValueError("Envie pelo menos um EPUB.")
    _validar_opcoes(
        opcoes.get("tamanho_pagina", TAMANHO_PADRAO),
        opcoes.get("margem_mm", 15),
        opcoes.get("tamanho_fonte", 11),
        opcoes.get("fonte", "Do livro"),
        opcoes.get("entrelinha", "Do livro"),
    )

    prontos: list[Arquivo] = []
    problemas: list[str] = []
    avisos: list[str] = []
    for posicao, (nome, dados) in enumerate(arquivos):
        _etapa(mostrar_etapas, f"livro {posicao + 1} de {len(arquivos)}: {nome}")

        def parcial(fracao: float, posicao=posicao) -> None:
            if progresso:
                progresso((posicao + fracao) / len(arquivos))

        try:
            resultado = epub_para_pdf(
                dados, progresso=parcial, mostrar_etapas=mostrar_etapas, **opcoes
            )
        except EpubInvalido as erro:
            problemas.append(f"{nome} ({erro})")
        except Exception as erro:  # noqa: BLE001 - um livro estranho não derruba o lote
            problemas.append(f"{nome} (erro inesperado do MuPDF: {erro})")
        else:
            prontos.append((nome_seguro(nome_base(nome)) + ".pdf", resultado.pdf))
            avisos.extend(f"{nome}: {aviso}" for aviso in resultado.avisos)
        parcial(1.0)
    return prontos, problemas, avisos
