"""Tela de conversão de livros EPUB para PDF."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import executar, mostrar_resultado, titulo


@st.cache_data(show_spinner=False, max_entries=32)
def _info(dados: bytes) -> pt.InfoEpub | str:
    """Dados do livro, ou o motivo de não dar para converter."""
    try:
        return pt.inspecionar_epub(dados)
    except pt.EpubInvalido as erro:
        return str(erro)
    except Exception as erro:  # noqa: BLE001 - arquivo estranho não derruba a tela
        return f"não consegui ler este EPUB ({erro})."


def _receber_epubs() -> list[tuple[str, bytes]]:
    enviados = st.file_uploader(
        "Escolha os livros EPUB (pode ser vários de uma vez)",
        type="epub",
        accept_multiple_files=True,
        key="upload_epub",
    )
    return [(arquivo.name, arquivo.getvalue()) for arquivo in enviados or []]


def _cartao_do_livro(nome: str, info: pt.InfoEpub) -> None:
    colunas = st.columns([3, 1, 1, 1])
    colunas[0].markdown(f"**{info.titulo or nome}**")
    detalhes = [parte for parte in (info.autor, info.editora) if parte]
    if detalhes:
        colunas[0].caption(" · ".join(detalhes))
    colunas[1].metric("Capítulos", info.capitulos)
    colunas[2].metric("Imagens", info.imagens)
    colunas[3].metric("Tamanho", pt.tamanho_legivel(info.tamanho))
    for aviso in info.avisos:
        st.caption(f"Atenção: {aviso}.")


def tela_epub_para_pdf() -> None:
    titulo(
        "📚",
        "EPUB para PDF",
        "Livros digitais viram PDF paginado, com sumário clicável e texto selecionável.",
    )

    arquivos = _receber_epubs()
    if not arquivos:
        st.caption(
            "Livros com DRM (comprados no Kindle, Kobo, Apple Livros...) não podem ser "
            "convertidos: o conteúdo vem cifrado pela loja. MOBI e AZW também não são EPUB."
        )
        return

    infos = [_info(dados) for _, dados in arquivos]
    validos = [
        (nome, dados, info)
        for (nome, dados), info in zip(arquivos, infos)
        if isinstance(info, pt.InfoEpub)
    ]
    for (nome, _), info in zip(arquivos, infos):
        if isinstance(info, str):
            st.warning(f"{nome}: {info} Fica de fora.")
    if not validos:
        return

    if len(validos) == 1:
        _cartao_do_livro(validos[0][0], validos[0][2])
    else:
        st.caption(f"{len(validos)} livros, {pt.tamanho_legivel(sum(i.tamanho for *_, i in validos))}.")

    st.subheader("Página")
    colunas = st.columns(2)
    tamanho_pagina = colunas[0].selectbox(
        "Tamanho",
        list(pt.TAMANHOS_PAGINA_EPUB),
        index=list(pt.TAMANHOS_PAGINA_EPUB).index(pt.TAMANHO_PADRAO_EPUB),
        key="epub_pagina",
        help="A5 é o tamanho de um livro comum. Para ler no celular ou num "
             "leitor digital, escolha Leitor digital.",
    )
    margem = colunas[1].slider(
        "Margem (mm)", 0, 40, 15, key="epub_margem",
        help="A mesma nos quatro lados. Para imprimir e encadernar, 20 mm ou mais.",
    )

    st.subheader("Texto")
    colunas = st.columns(3)
    tamanho_fonte = colunas[0].slider(
        "Tamanho da letra (pt)", 8, 20, 11, key="epub_fonte_tamanho",
        help="11 pt em A5 lembra um livro impresso. Títulos crescem na mesma proporção.",
    )
    fonte = colunas[1].selectbox(
        "Fonte", list(pt.FONTES_EPUB), key="epub_fonte",
        help="Do livro mantém a fonte que a editora escolheu.",
    )
    entrelinha = colunas[2].selectbox(
        "Entrelinha", list(pt.ENTRELINHAS), key="epub_entrelinha",
    )
    justificar = st.checkbox(
        "Justificar os parágrafos", key="epub_justificar",
        help="Alinha o texto nas duas margens, como em livro impresso.",
    )

    with st.expander("Avançado"):
        estilo_do_livro = st.checkbox(
            "Usar o estilo do livro", value=True, key="epub_estilo",
            help="Desmarque se o PDF sair com letra minúscula, cor ilegível ou "
                 "espaçamento estranho: aí só valem as opções acima.",
        )
        sumario = st.checkbox(
            "Sumário como marcadores", value=True, key="epub_sumario",
            help="Os capítulos aparecem no painel lateral do leitor de PDF.",
        )
        links = st.checkbox(
            "Links clicáveis", value=True, key="epub_links",
            help="Notas de rodapé, índice remissivo e links para sites.",
        )

    opcoes = {
        "tamanho_pagina": tamanho_pagina,
        "margem_mm": margem,
        "tamanho_fonte": tamanho_fonte,
        "fonte": fonte,
        "entrelinha": entrelinha,
        "justificar": justificar,
        "estilo_do_livro": estilo_do_livro,
        "sumario": sumario,
        "links": links,
    }
    assinatura = "|".join(f"{nome}:{len(dados)}" for nome, dados, _ in validos)
    assinatura += repr(sorted(opcoes.items()))
    quantos = len(validos)
    rotulo = "Converter para PDF" if quantos == 1 else f"Converter {quantos} livros para PDF"

    if st.button(rotulo, type="primary", width="stretch"):
        barra = st.progress(0.0, text="Paginando...")

        def rodar():
            prontos, problemas, avisos = pt.converter_epubs_lote(
                [(nome, dados) for nome, dados, _ in validos],
                progresso=lambda f: barra.progress(min(f, 1.0), text="Convertendo..."),
                **opcoes,
            )
            if not prontos:
                raise ValueError("Nenhum livro pôde ser convertido: " + "; ".join(problemas))
            paginas = sum(pt.contar_paginas(conteudo) for _, conteudo in prontos)
            total = sum(len(conteudo) for _, conteudo in prontos)
            resumo = (
                f"{len(prontos)} PDF(s), {paginas} página(s), "
                f"{pt.tamanho_legivel(total)} no total."
            )
            if avisos:
                resumo += " Observações: " + "; ".join(avisos) + "."
            if problemas:
                resumo += " Ficaram de fora: " + "; ".join(problemas)
            return prontos, resumo

        with st.spinner("Convertendo..."):
            executar("epub", assinatura, rodar)
        barra.empty()

    mostrar_resultado("epub", assinatura, nome_do_zip="livros-pdf.zip")
