"""Telas de marca d'água e numeração de páginas."""

from __future__ import annotations

import io

import streamlit as st

import pdf_tools as pt

from .comum import (
    campo_intervalo,
    executar,
    mostrar_resultado,
    receber_pdf,
    titulo,
)


@st.cache_data(show_spinner=False, max_entries=12)
def _previa(dados: bytes, senha: str, pagina: int, operacao: str, parametros: dict) -> bytes:
    """Renderiza como fica UMA página, para o usuário mirar antes de aplicar.

    A página é recortada antes de receber a marca: assim o custo da prévia não
    depende do tamanho do documento, e um PDF de 500 páginas responde na hora.
    """
    unica = pt.extrair(dados, str(pagina + 1), senha)
    if operacao == "texto":
        marcada = pt.marca_dagua_texto(unica, **parametros)
    elif operacao == "imagem":
        marcada = pt.marca_dagua_imagem(unica, **parametros)
    else:
        marcada = pt.numerar_paginas(unica, **parametros)
    imagem = pt.renderizar_pagina(marcada, 0, dpi=110)
    buffer = io.BytesIO()
    imagem.save(buffer, "PNG")
    return buffer.getvalue()


def _mostrar_previa(entrada, operacao: str, parametros: dict, pagina: int) -> None:
    coluna_previa = st.container()
    try:
        png = _previa(entrada.dados, entrada.senha, pagina, operacao, parametros)
    except Exception as erro:
        coluna_previa.caption(f"Não consegui gerar a prévia: {erro}")
        return
    esquerda, meio, direita = coluna_previa.columns([1, 2, 1])
    meio.image(png, caption=f"Prévia — página {pagina + 1}", width="stretch")


def _seletor_de_pagina(entrada, chave: str) -> int:
    if entrada.paginas == 1:
        return 0
    return st.number_input(
        "Página da prévia", min_value=1, max_value=entrada.paginas, value=1,
        step=1, key=f"previa_{chave}",
    ) - 1


# --------------------------------------------------------------------------


def tela_marca_dagua() -> None:
    titulo("💧", "Marca d'água", "Carimbe um texto ou um logo por cima (ou por baixo) do conteúdo.")

    entrada = receber_pdf("marca")
    if entrada is None:
        return

    # O Streamlit desenha as duas abas no mesmo rerun, entao cada uma precisa
    # da sua propria chave de resultado: chaves iguais colidem no download.
    aba_texto, aba_imagem = st.tabs(["Texto", "Imagem"])

    with aba_texto:
        _marca_texto(entrada)
    with aba_imagem:
        _marca_imagem(entrada)


def _marca_texto(entrada) -> None:
    texto = st.text_input("Texto", value="CONFIDENCIAL", key="marca_texto")

    colunas = st.columns(3)
    fonte = colunas[0].selectbox("Fonte", pt.FONTES, index=1, key="marca_fonte")
    tamanho = colunas[1].slider("Tamanho", 10, 150, 60, key="marca_tamanho")
    cor = colunas[2].color_picker("Cor", "#D32F2F", key="marca_cor")

    colunas = st.columns(3)
    opacidade = colunas[0].slider("Opacidade", 0.05, 1.0, 0.18, step=0.01, key="marca_op")
    angulo = colunas[1].slider("Inclinação", -90, 90, 45, key="marca_ang")
    mosaico = colunas[2].checkbox(
        "Repetir pela página toda", value=False, key="marca_mosaico",
        help="Preenche a página inteira com o texto repetido.",
    )

    colunas = st.columns(2)
    posicao = colunas[0].selectbox(
        "Posição", pt.POSICOES, key="marca_pos", disabled=mosaico,
        help="Ignorado quando o texto se repete pela página.",
    )
    atras = colunas[1].checkbox(
        "Colocar atrás do conteúdo", value=False, key="marca_atras",
        help="Deixa o texto do documento por cima da marca — fica mais discreto.",
    )

    intervalo = campo_intervalo("marca_texto", entrada.paginas)
    parametros = dict(
        texto=texto, fonte=fonte, tamanho=tamanho, cor=cor, opacidade=opacidade,
        angulo=angulo, mosaico=mosaico, posicao=posicao, atras=atras,
    )

    if texto.strip():
        pagina = _seletor_de_pagina(entrada, "marca_texto")
        _mostrar_previa(entrada, "texto", {**parametros, "intervalo": ""}, pagina)

    if st.button("Aplicar marca d'água", type="primary", width="stretch",
                 key="btn_marca_texto"):
        def rodar():
            dados = pt.marca_dagua_texto(
                entrada.dados, intervalo=intervalo, senha=entrada.senha, **parametros
            )
            alvos = len(pt.parse_intervalo(intervalo, entrada.paginas))
            return (
                [(pt.sufixar(entrada.nome, "marca-dagua"), dados)],
                f"Marca aplicada em {alvos} página(s).",
            )

        with st.spinner("Aplicando..."):
            executar("marca_texto", entrada.assinatura, rodar)

    mostrar_resultado("marca_texto", entrada.assinatura)


def _marca_imagem(entrada) -> None:
    enviada = st.file_uploader(
        "Logo ou assinatura", type=["png", "jpg", "jpeg", "webp"], key="marca_logo"
    )
    if enviada is None:
        st.caption("Envie um PNG com fundo transparente para o melhor resultado.")
        return
    logo = enviada.getvalue()

    colunas = st.columns(3)
    largura = colunas[0].slider(
        "Largura", 0.05, 1.0, 0.35, step=0.05, key="logo_larg",
        help="Fração da largura da página que a imagem ocupa.",
    )
    opacidade = colunas[1].slider("Opacidade", 0.05, 1.0, 0.35, step=0.05, key="logo_op")
    angulo = colunas[2].slider("Inclinação", -90, 90, 0, key="logo_ang")

    colunas = st.columns(2)
    posicao = colunas[0].selectbox("Posição", pt.POSICOES, key="logo_pos")
    atras = colunas[1].checkbox("Colocar atrás do conteúdo", value=True, key="logo_atras")

    intervalo = campo_intervalo("marca_logo", entrada.paginas)
    parametros = dict(
        imagem=logo, largura_relativa=largura, opacidade=opacidade,
        posicao=posicao, angulo=angulo, atras=atras,
    )

    pagina = _seletor_de_pagina(entrada, "marca_logo")
    _mostrar_previa(entrada, "imagem", {**parametros, "intervalo": ""}, pagina)

    if st.button("Aplicar logo", type="primary", width="stretch",
                 key="btn_marca_logo"):
        def rodar():
            dados = pt.marca_dagua_imagem(
                entrada.dados, intervalo=intervalo, senha=entrada.senha, **parametros
            )
            alvos = len(pt.parse_intervalo(intervalo, entrada.paginas))
            return (
                [(pt.sufixar(entrada.nome, "com-logo"), dados)],
                f"Logo aplicado em {alvos} página(s).",
            )

        with st.spinner("Aplicando..."):
            executar("marca_logo", entrada.assinatura, rodar)

    mostrar_resultado("marca_logo", entrada.assinatura)


# --------------------------------------------------------------------------


MODELOS = {
    "1": "{n}",
    "1 / 20": "{n} / {total}",
    "Página 1": "Página {n}",
    "Página 1 de 20": "Página {n} de {total}",
    "- 1 -": "- {n} -",
    "Personalizado": "",
}


def tela_numerar() -> None:
    titulo("🔢", "Numerar páginas", "Adicione o número da página no rodapé ou no cabeçalho.")

    entrada = receber_pdf("numerar")
    if entrada is None:
        return

    colunas = st.columns(2)
    modelo = colunas[0].selectbox("Formato", list(MODELOS), index=0, key="num_modelo")
    if modelo == "Personalizado":
        formato = colunas[1].text_input(
            "Escreva o formato", value="Página {n} de {total}",
            help="Use {n} para o número da página e {total} para o último número.",
        )
    else:
        formato = MODELOS[modelo]
        colunas[1].text_input("Formato usado", value=formato, disabled=True)

    colunas = st.columns(3)
    posicao = colunas[0].selectbox(
        "Posição", pt.POSICOES, index=1, key="num_pos",
        help="'Alternado (livro)' joga o número para a borda externa, "
             "como em livro impresso.",
    )
    fonte = colunas[1].selectbox("Fonte", pt.FONTES, key="num_fonte")
    tamanho = colunas[2].slider("Tamanho", 6, 24, 10, key="num_tam")

    colunas = st.columns(3)
    cor = colunas[0].color_picker("Cor", "#444444", key="num_cor")
    margem = colunas[1].slider("Margem (mm)", 4, 40, 12, key="num_margem")
    comecar = colunas[2].number_input(
        "Começar na página", min_value=1, max_value=entrada.paginas, value=1, step=1,
        key="num_comeca", help="Deixe em 2 para não numerar a capa.",
    )
    primeiro = st.number_input(
        "Primeiro número impresso", min_value=0, value=1, step=1, key="num_primeiro",
        help="Continua a numeração de outro caderno: comece em 47, por exemplo.",
    )

    parametros = dict(
        formato=formato, posicao=posicao, fonte=fonte, tamanho=tamanho,
        cor=cor, margem_mm=margem,
    )

    numeradas = entrada.paginas - int(comecar) + 1
    st.caption(
        f"{numeradas} página(s) numeradas, de {primeiro} a "
        f"{int(primeiro) + numeradas - 1}."
    )

    if "{n}" in formato or "{total}" in formato:
        pagina = _seletor_de_pagina(entrada, "numerar")
        # A prévia usa uma página só, então o número mostrado é o que aquela
        # página receberia no documento inteiro.
        numero_na_previa = max(int(primeiro) + (pagina - int(comecar) + 1), int(primeiro))
        _mostrar_previa(
            entrada, "numerar",
            {**parametros, "primeiro_numero": numero_na_previa,
             "comecar_na_pagina": 1,
             "formato": formato.replace("{total}", str(int(primeiro) + numeradas - 1))},
            pagina,
        )

    if st.button("Numerar", type="primary", width="stretch"):
        def rodar():
            dados = pt.numerar_paginas(
                entrada.dados, senha=entrada.senha,
                primeiro_numero=int(primeiro), comecar_na_pagina=int(comecar),
                **parametros,
            )
            return (
                [(pt.sufixar(entrada.nome, "numerado"), dados)],
                f"{numeradas} página(s) numeradas.",
            )

        with st.spinner("Numerando..."):
            executar("numerar", entrada.assinatura, rodar)

    mostrar_resultado("numerar", entrada.assinatura)
