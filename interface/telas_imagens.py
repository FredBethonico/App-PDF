"""Tela de redimensionamento de imagens em lote."""

from __future__ import annotations

import io

import streamlit as st
from PIL import Image, ImageOps

import pdf_tools as pt

from .comum import executar, mostrar_resultado, receber_imagens, titulo

MODOS = {
    "Largura e altura exatas": "exato",
    "Só a largura": "largura",
    "Só a altura": "altura",
    "Lado maior": "lado_maior",
}

ENCAIXES = {
    "Cortar o que sobrar": (
        "cortar",
        "Preenche o tamanho inteiro sem distorcer. O que passar das bordas é "
        "cortado, mantendo o centro da imagem.",
    ),
    "Caber inteira, com fundo": (
        "fundo",
        "A imagem aparece completa, sem distorcer. O espaço que sobrar vira "
        "uma faixa de fundo.",
    ),
    "Esticar": (
        "esticar",
        "Força a imagem no tamanho exato. Se a proporção for diferente, ela "
        "fica achatada ou esticada.",
    ),
}

FORMATOS = {
    "Mesmo do original": "original",
    "PNG": "PNG",
    "JPEG": "JPEG",
    "WEBP": "WEBP",
}

_LADO_PREVIA = 420  # px; a prévia não precisa trafegar a imagem em tamanho real
_EXTENSOES_COM_QUALIDADE = (".jpg", ".jpeg", ".webp")


def _px(tamanho: tuple[int, int]) -> str:
    return f"{tamanho[0]} × {tamanho[1]} px"


@st.cache_data(show_spinner=False, max_entries=128)
def _dimensoes(dados: bytes) -> tuple[int, int] | None:
    try:
        return pt.dimensoes_imagem(dados)
    except Exception:
        return None


def _miniatura(dados: bytes) -> bytes:
    with Image.open(io.BytesIO(dados)) as aberta:
        imagem = ImageOps.exif_transpose(aberta)
    imagem.thumbnail((_LADO_PREVIA, _LADO_PREVIA))
    buffer = io.BytesIO()
    imagem.convert("RGBA").save(buffer, "PNG")
    return buffer.getvalue()


@st.cache_data(show_spinner="Gerando prévia...", max_entries=16)
def _previa(dados: bytes, opcoes: dict) -> tuple[bytes, bytes, tuple[int, int]]:
    """(antes, depois, tamanho final) da primeira imagem, em miniatura."""
    depois, _, tamanho = pt.redimensionar_imagem(dados, **opcoes)
    return _miniatura(dados), _miniatura(depois), tamanho


def _campo_px(alvo, rotulo: str, padrao: int, chave: str) -> int:
    return int(
        alvo.number_input(
            rotulo,
            min_value=1,
            max_value=pt.LADO_MAXIMO,
            value=min(int(padrao), pt.LADO_MAXIMO),
            step=1,
            key=chave,
        )
    )


def _descrever_tamanhos(tamanhos: list[tuple[int, int]], singular: str, plural: str) -> str:
    """'Todas vão ficar com 800 × 600 px', ou a faixa quando os tamanhos variam."""
    unicos = set(tamanhos)
    if len(unicos) == 1:
        if len(tamanhos) == 1:
            return f"A imagem {singular} {_px(tamanhos[0])}."
        return f"Todas {plural} {_px(tamanhos[0])}."
    larguras = {t[0] for t in tamanhos}
    alturas = {t[1] for t in tamanhos}
    if len(larguras) == 1:
        return (
            f"Todas com {next(iter(larguras))} px de largura; a altura vai de "
            f"{min(alturas)} a {max(alturas)} px."
        )
    if len(alturas) == 1:
        return (
            f"Todas com {next(iter(alturas))} px de altura; a largura vai de "
            f"{min(larguras)} a {max(larguras)} px."
        )
    por_area = sorted(unicos, key=lambda t: t[0] * t[1])
    return f"Os tamanhos vão de {_px(por_area[0])} a {_px(por_area[-1])}."


# --------------------------------------------------------------------------


def tela_redimensionar() -> None:
    titulo(
        "📐",
        "Redimensionar imagens",
        "Envie uma ou várias imagens, digite o tamanho em pixels e baixe todas prontas.",
    )

    arquivos = receber_imagens("redim", "Escolha as imagens (pode ser várias de uma vez)")
    if not arquivos:
        st.caption(
            "Formatos aceitos: " + ", ".join(f.upper() for f in pt.FORMATOS_ENTRADA) + "."
        )
        return

    medidas = [_dimensoes(dados) for _, dados in arquivos]
    legiveis = [
        (nome, dados, medida)
        for (nome, dados), medida in zip(arquivos, medidas)
        if medida is not None
    ]
    ilegiveis = [nome for (nome, _), medida in zip(arquivos, medidas) if medida is None]
    if ilegiveis:
        st.warning("Não consegui abrir: " + ", ".join(ilegiveis) + ". Elas ficam de fora.")
    if not legiveis:
        return

    st.subheader(f"{len(legiveis)} imagem(ns)")
    atual = _descrever_tamanhos([m for *_, m in legiveis], "tem", "têm")
    st.caption("Hoje: " + atual[0].lower() + atual[1:])

    st.subheader("Novo tamanho")
    modo = MODOS[st.radio("Como definir", list(MODOS), horizontal=True, key="redim_modo")]
    referencia = legiveis[0][2]
    opcoes: dict = {"modo": modo}

    if modo == "exato":
        colunas = st.columns(2)
        opcoes["largura"] = _campo_px(colunas[0], "Largura (px)", referencia[0], "redim_largura")
        opcoes["altura"] = _campo_px(colunas[1], "Altura (px)", referencia[1], "redim_altura")
    elif modo == "largura":
        opcoes["largura"] = _campo_px(st, "Largura (px)", referencia[0], "redim_largura")
        st.caption("A altura de cada imagem acompanha, para não distorcer.")
    elif modo == "altura":
        opcoes["altura"] = _campo_px(st, "Altura (px)", referencia[1], "redim_altura")
        st.caption("A largura de cada imagem acompanha, para não distorcer.")
    else:
        opcoes["lado"] = _campo_px(st, "Lado maior (px)", max(referencia), "redim_lado")
        st.caption(
            "O lado mais comprido de cada imagem fica com essa medida — "
            "vale igual para foto em pé e deitada."
        )

    if modo == "exato":
        proporcao = opcoes["largura"] / opcoes["altura"]
        diferentes = sum(
            1 for *_, (larg, alt) in legiveis if abs(larg / alt - proporcao) > 0.01
        )
        if diferentes:
            st.caption(
                f"{diferentes} de {len(legiveis)} imagem(ns) têm proporção diferente "
                f"de {opcoes['largura']} × {opcoes['altura']}. Escolha o que fazer com elas:"
            )
        rotulo = st.radio("Quando a proporção não bater", list(ENCAIXES), key="redim_encaixe")
        opcoes["encaixe"], explicacao = ENCAIXES[rotulo]
        st.caption(explicacao)
        if opcoes["encaixe"] == "fundo":
            colunas = st.columns(2)
            opcoes["fundo"] = colunas[0].color_picker("Cor do fundo", "#FFFFFF", key="redim_fundo")
            opcoes["transparente"] = colunas[1].checkbox(
                "Fundo transparente",
                key="redim_transparente",
                help="Só funciona em PNG e WEBP. Em JPEG o fundo usa a cor escolhida.",
            )
    else:
        opcoes["nao_ampliar"] = st.checkbox(
            "Não aumentar as que já são menores",
            key="redim_nao_ampliar",
            help="Imagens menores que o tamanho escolhido ficam como estão, "
                 "em vez de serem esticadas e saírem borradas.",
        )

    st.subheader("Arquivo de saída")
    colunas = st.columns(2)
    opcoes["formato"] = FORMATOS[
        colunas[0].selectbox(
            "Formato",
            list(FORMATOS),
            key="redim_formato",
            help="'Mesmo do original' mantém PNG como PNG e JPEG como JPEG. "
                 "BMP, TIFF e GIF viram PNG.",
        )
    ]
    usa_qualidade = opcoes["formato"] in ("JPEG", "WEBP") or (
        opcoes["formato"] == "original"
        and any(nome.lower().endswith(_EXTENSOES_COM_QUALIDADE) for nome, *_ in legiveis)
    )
    if usa_qualidade:
        opcoes["qualidade"] = colunas[1].slider(
            "Qualidade (JPEG/WEBP)", 50, 100, 90, key="redim_qualidade",
            help="90 é praticamente igual ao original. Abaixo de 70 começam a aparecer manchas.",
        )
    if opcoes["formato"] == "JPEG":
        st.caption(
            "JPEG não guarda transparência: áreas transparentes saem preenchidas "
            "com a cor de fundo (branco, se você não escolheu outra)."
        )

    medidas_opcoes = {
        chave: valor for chave, valor in opcoes.items()
        if chave in ("modo", "largura", "altura", "lado", "nao_ampliar")
    }
    finais = [pt.tamanho_redimensionado(m, **medidas_opcoes) for *_, m in legiveis]
    st.info(_descrever_tamanhos(finais, "vai ficar com", "vão ficar com"))

    ampliadas = sum(
        1 for (*_, atual), final in zip(legiveis, finais)
        if final[0] > atual[0] or final[1] > atual[1]
    )
    if ampliadas:
        st.warning(
            f"{ampliadas} imagem(ns) vão ser aumentadas além do tamanho original "
            "e podem ficar borradas."
        )
    grandes = sum(1 for final in finais if max(final) > pt.LADO_MAXIMO)
    if grandes:
        st.warning(
            f"{grandes} imagem(ns) passariam de {pt.LADO_MAXIMO:,} px por lado e vão "
            "ficar de fora.".replace(",", ".")
        )

    with st.expander("Prévia da primeira imagem", expanded=True):
        try:
            antes, depois, tamanho = _previa(legiveis[0][1], opcoes)
        except Exception as erro:
            st.caption(f"Não consegui gerar a prévia: {erro}")
        else:
            esquerda, direita = st.columns(2)
            esquerda.image(antes, caption=f"Antes — {_px(legiveis[0][2])}", width="stretch")
            direita.image(depois, caption=f"Depois — {_px(tamanho)}", width="stretch")

    # As opções entram na assinatura: mudar o tamanho esconde o resultado antigo,
    # em vez de oferecer para baixar imagens de um tamanho que não é mais o da tela.
    assinatura = "|".join(f"{nome}:{len(dados)}" for nome, dados, _ in legiveis)
    assinatura += repr(sorted(opcoes.items()))
    quantas = len(legiveis)
    rotulo_botao = "Redimensionar" if quantas == 1 else f"Redimensionar {quantas} imagens"

    if st.button(rotulo_botao, type="primary", width="stretch"):
        barra = st.progress(0.0, text="Redimensionando...")

        def rodar():
            prontos, problemas = pt.redimensionar_lote(
                [(nome, dados) for nome, dados, _ in legiveis],
                progresso=lambda f: barra.progress(f, text="Redimensionando..."),
                **opcoes,
            )
            if not prontos:
                raise ValueError(
                    "Nenhuma imagem pôde ser redimensionada: " + "; ".join(problemas)
                )
            total = sum(len(conteudo) for _, conteudo in prontos)
            resumo = f"{len(prontos)} imagem(ns) pronta(s), {pt.tamanho_legivel(total)} no total."
            if problemas:
                resumo += " Ficaram de fora: " + "; ".join(problemas) + "."
            return prontos, resumo

        with st.spinner("Redimensionando..."):
            executar("redim", assinatura, rodar)
        barra.empty()

    mostrar_resultado(
        "redim", assinatura, nome_do_zip="imagens-redimensionadas.zip", previa=False
    )
