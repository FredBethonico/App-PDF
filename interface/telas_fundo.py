"""Tela de remover fundo: automático, retoque a pincel e saída transparente ou em cor."""

from __future__ import annotations

import hashlib

import streamlit as st

import pdf_tools as pt

from .comum import TIPO_IMAGEM, executar, mostrar_resultado, titulo

METODOS = {
    "Inteligência artificial": (
        "ia",
        "Acha sozinha a pessoa, o bicho ou o objeto principal. Boa para fotos "
        "com fundo bagunçado.",
    ),
    "Cor do fundo": (
        "cor",
        "Apaga uma cor só. Ideal para logo, assinatura, print e foto de produto "
        "em fundo liso — a borda sai mais limpa que na IA.",
    ),
    "Nenhuma (só o pincel)": (
        "nenhum",
        "Começa com a imagem inteira e você apaga à mão o que quiser.",
    ),
}

PINCEIS = {
    "🔴 Apagar": "rgba(235, 40, 40, 0.55)",
    "🟢 Restaurar": "rgba(20, 200, 70, 0.55)",
}

_CAIXA_PINCEL = (560, 560)  # o canvas cabe na coluna sem rolar na maioria das telas
_LADO_PREVIA = 900
_FRACAO_FUNDO_LISO = 0.95


@st.cache_data(show_spinner="Preparando a foto...", max_entries=4)
def _caber_no_limite(dados: bytes) -> tuple[bytes, tuple[int, int] | None]:
    return pt.caber_no_limite(dados)


def _dimensoes(dados: bytes) -> str:
    largura, altura = pt.dimensoes_imagem(dados)
    return f"{largura} × {altura}"


@st.cache_data(show_spinner=False, max_entries=8)
def _analise(dados: bytes) -> tuple[str, float]:
    return pt.analisar_fundo(dados)


@st.cache_data(show_spinner=False, max_entries=8)
def _mascara_auto(
    dados: bytes, metodo: str, modelo: str, cor: str, tolerancia: int, so_bordas: bool
) -> bytes:
    if metodo == "ia":
        return pt.mascara_ia(dados, modelo)
    if metodo == "cor":
        return pt.mascara_por_cor(dados, cor=cor, tolerancia=tolerancia, so_pelas_bordas=so_bordas)
    return pt.mascara_vazia(dados)


@st.cache_data(show_spinner=False, max_entries=8)
def _fantasma(dados: bytes, mascara: bytes) -> tuple[bytes, tuple[int, int]]:
    return pt.previa_fantasma(dados, mascara, _CAIXA_PINCEL)


@st.cache_data(show_spinner=False, max_entries=4)
def _reduzida(dados: bytes) -> tuple[bytes, float]:
    return pt.reduzir(dados, _LADO_PREVIA)


@st.cache_data(show_spinner=False, max_entries=16)
def _previa_final(dados: bytes, mascara: bytes, opcoes: tuple) -> bytes:
    """Resultado em miniatura: roda na cópia reduzida para responder rápido a cada pincelada."""
    pequena, fator = _reduzida(dados)
    ajustes = dict(opcoes)
    # Encolher/suavizar são em px da imagem original: na cópia reduzida, proporcionais.
    ajustes["encolher"] = round(ajustes.get("encolher", 0) * fator)
    ajustes["suavizar"] = ajustes.get("suavizar", 0) * fator
    ajustes["margem"] = round(ajustes.get("margem", 0) * fator)
    ajustes["formato"] = "PNG"
    resultado, _, _ = pt.remover_fundo(pequena, mascara, **ajustes)
    return pt.previa_resultado(resultado, _LADO_PREVIA)


def _carregar_canvas():
    """O pincel vem de um componente à parte; sem ele, a tela segue só com o automático."""
    try:
        from streamlit_drawable_canvas import st_canvas
    except Exception:
        return None
    return st_canvas


# --------------------------------------------------------------------------


def _passo_automatico(dados: bytes, sufixo: str) -> tuple[bytes, str | None] | None:
    """Escolha do método e cálculo da máscara. Devolve (máscara, cor apagada)."""
    st.subheader("1. Remoção automática")
    cor_borda, fracao = _analise(dados)
    sugerido = "Cor do fundo" if fracao >= _FRACAO_FUNDO_LISO else "Inteligência artificial"

    rotulo = st.radio(
        "Como remover",
        list(METODOS),
        index=list(METODOS).index(sugerido),
        horizontal=True,
        key=f"fundo_metodo_{sufixo}",
    )
    metodo, explicacao = METODOS[rotulo]
    st.caption(explicacao)
    if metodo == "cor" and fracao < _FRACAO_FUNDO_LISO:
        st.caption(
            "As bordas desta imagem têm cores variadas; se sobrar muito fundo, "
            "experimente a inteligência artificial."
        )

    modelo, cor, tolerancia, so_bordas = pt.MODELO_PADRAO, cor_borda, 12, True
    if metodo == "ia":
        nomes = {f"{rotulo} ({tamanho})": nome for nome, (rotulo, tamanho) in pt.MODELOS_IA.items()}
        modelo = nomes[
            st.radio(
                "Modelo",
                list(nomes),
                horizontal=True,
                key="fundo_modelo",
                help="O detalhado acerta mais em cabelo e em objetos finos, mas "
                     "demora mais e usa mais memória. Na primeira vez o modelo é "
                     "baixado para o servidor (só uma vez).",
            )
        ]
    elif metodo == "cor":
        colunas = st.columns([1, 2])
        cor = colunas[0].color_picker(
            "Cor a apagar", cor_borda, key=f"fundo_cor_alvo_{sufixo}",
            help="Já vem com a cor mais comum nas bordas da imagem.",
        )
        tolerancia = colunas[1].slider(
            "Tolerância", 0, 60, 12, key="fundo_tolerancia",
            help="Quanto uma cor pode ser diferente da escolhida e ainda ser apagada. "
                 "Aumente se sobrar sombra ou ruído de JPEG; diminua se começar a "
                 "comer o desenho.",
        )
        so_bordas = not st.checkbox(
            "Apagar essa cor também no meio do desenho",
            key="fundo_miolo",
            help="Desmarcado, só some o fundo que encosta nas bordas. Marque para "
                 "apagar também o miolo de letras como O, A e B num logo.",
        )

    try:
        with st.spinner(
            "Removendo o fundo..." if metodo != "ia"
            else "Removendo o fundo com IA (na primeira vez baixa o modelo)..."
        ):
            mascara = _mascara_auto(dados, metodo, modelo, cor, tolerancia, so_bordas)
    except ValueError as erro:
        st.error(str(erro))
        return None
    except Exception as erro:
        st.error(f"Não consegui remover o fundo: {erro}")
        return None
    return mascara, (cor if metodo == "cor" else None)


def _passo_pincel(dados: bytes, mascara: bytes, sufixo: str, alvo) -> bytes:
    """Canvas para apagar/restaurar à mão. Devolve o PNG dos traços (ou None)."""
    st_canvas = _carregar_canvas()
    if st_canvas is None:
        alvo.info(
            "O pincel não está disponível neste servidor (falta o pacote "
            "streamlit-drawable-canvas). O resultado usa só a remoção automática."
        )
        return None

    colunas = alvo.columns([3, 2])
    pincel = colunas[0].radio("Pincel", list(PINCEIS), horizontal=True, key="fundo_pincel")
    espessura = colunas[1].slider("Tamanho", 4, 80, 24, key="fundo_espessura")

    contador = f"fundo_limpezas_{sufixo}"
    st.session_state.setdefault(contador, 0)
    fundo_canvas, (largura, altura) = _fantasma(dados, mascara)
    with alvo:
        resultado = st_canvas(
            stroke_width=espessura,
            stroke_color=PINCEIS[pincel],
            background_image=fundo_canvas,
            width=largura,
            height=altura,
            drawing_mode="freedraw",
            return_image_data=True,
            key=f"fundo_canvas_{sufixo}_{st.session_state[contador]}",
        )
    alvo.caption(
        "Pinte em vermelho o que ainda sobrou de fundo e em verde o que a remoção "
        "levou por engano. A parte apagadinha é o que vai sumir. "
        "Desfazer e refazer ficam na barra do quadro."
    )
    if alvo.button("Limpar pinceladas", key="fundo_limpar"):
        st.session_state[contador] += 1
        st.rerun()

    try:
        return resultado.image_bytes if resultado is not None else None
    except Exception:  # canvas ainda sem desenho nenhum
        return None


def _passo_saida(metodo_cor: str | None) -> dict:
    st.subheader("3. Fundo final")
    colunas = st.columns(2)
    tipo = colunas[0].radio(
        "Fundo",
        ["Transparente", "Cor sólida"],
        horizontal=True,
        key="fundo_tipo",
        help="Transparente encaixa em qualquer lugar (slides, sites, outros "
             "editores). Cor sólida serve para app que não aceita transparência.",
    )
    opcoes: dict = {"fundo": "transparente" if tipo == "Transparente" else "cor"}
    if opcoes["fundo"] == "cor":
        opcoes["cor"] = colunas[1].color_picker("Cor do fundo", "#FFFFFF", key="fundo_cor_saida")
        formatos = ["PNG", "JPEG", "WEBP"]
    else:
        formatos = ["PNG", "WEBP"]
    colunas = st.columns(2)
    opcoes["formato"] = colunas[0].selectbox(
        "Formato",
        formatos,
        key=f"fundo_formato_{opcoes['fundo']}",
        help="PNG funciona em todo lugar. WEBP fica bem menor. JPEG não tem "
             "transparência, por isso só aparece com cor sólida.",
    )
    opcoes["recortar"] = colunas[1].checkbox(
        "Recortar o espaço vazio em volta",
        key="fundo_recortar",
        help="A imagem final fica do tamanho do que sobrou, sem a área vazia.",
    )
    if opcoes["recortar"]:
        opcoes["margem"] = colunas[1].number_input(
            "Margem (px)", 0, 500, 0, step=5, key="fundo_margem"
        )

    with st.expander("Ajuste fino da borda"):
        opcoes["encolher"] = st.slider(
            "Encolher a borda (px)", 0, 10, 0, key="fundo_encolher",
            help="Come uns pixels do contorno. Tira aquela linha fina do fundo "
                 "antigo que às vezes fica grudada.",
        )
        opcoes["suavizar"] = st.slider(
            "Suavizar a borda (px)", 0.0, 10.0, 0.0, step=0.5, key="fundo_suavizar",
            help="Desfoca o contorno para o recorte não ficar com cara de tesoura.",
        )
    if metodo_cor:
        opcoes["cor_removida"] = metodo_cor  # limpa o halo da cor antiga nas bordas
    return opcoes


# --------------------------------------------------------------------------


def tela_remover_fundo() -> None:
    titulo(
        "🪄",
        "Remover fundo",
        "Tira o fundo da imagem sozinho, você retoca com o pincel e baixa com "
        "fundo transparente ou em cor sólida.",
    )

    enviado = st.file_uploader("Escolha a imagem", type=TIPO_IMAGEM, key="upload_fundo")
    if enviado is None:
        st.caption(
            "Formatos aceitos: " + ", ".join(f.upper() for f in pt.FORMATOS_ENTRADA) + "."
        )
        return
    try:
        dados, tamanho_original = _caber_no_limite(enviado.getvalue())
        _analise(dados)
    except ValueError as erro:
        st.error(str(erro))
        return
    except Exception:
        st.error(
            "Não consegui abrir essa imagem. O formato pode não ser suportado "
            "ou o arquivo está corrompido."
        )
        return

    if tamanho_original:
        st.info(
            f"A foto tem {tamanho_original[0]} × {tamanho_original[1]} px, acima do limite "
            f"de {pt.MEGAPIXELS_MAXIMO} megapixels desta ferramenta. Reduzi para "
            f"{_dimensoes(dados)} px, que ainda sobra para tela e impressão comum."
        )

    sufixo = hashlib.md5(dados).hexdigest()[:10]
    automatico = _passo_automatico(dados, sufixo)
    if automatico is None:
        return
    mascara_auto, cor_apagada = automatico

    st.subheader("2. Retoque com o pincel")
    esquerda, direita = st.columns(2, gap="medium")
    tracos = _passo_pincel(dados, mascara_auto, sufixo, esquerda)
    mascara = pt.aplicar_pinceladas(mascara_auto, tracos)

    with direita:
        previa = st.empty()

    opcoes = _passo_saida(cor_apagada)
    try:
        miniatura = _previa_final(dados, mascara, tuple(sorted(opcoes.items())))
    except ValueError as erro:
        previa.warning(str(erro))
    else:
        previa.image(miniatura, caption="Como vai ficar", width="stretch")

    nome_base = pt.nome_base(enviado.name)
    sufixo_nome = "sem-fundo" if opcoes["fundo"] == "transparente" else "fundo-" + opcoes["cor"].lstrip("#").lower()
    assinatura = hashlib.md5(
        dados[:200_000] + mascara + repr(sorted(opcoes.items())).encode()
    ).hexdigest()

    if st.button("Gerar imagem", type="primary", width="stretch"):
        def rodar():
            conteudo, extensao, (largura, altura) = pt.remover_fundo(dados, mascara, **opcoes)
            nome = pt.nome_seguro(f"{nome_base}-{sufixo_nome}") + extensao
            resumo = f"{largura} × {altura} px, {pt.tamanho_legivel(len(conteudo))}."
            return [(nome, conteudo)], resumo

        with st.spinner("Montando a imagem..."):
            executar("fundo", assinatura, rodar)

    mostrar_resultado("fundo", assinatura, previa=False)
