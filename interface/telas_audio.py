"""Tela de conversão de vídeo (MP4 e afins) para MP3."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import executar, mostrar_resultado, titulo

QUALIDADES = {
    "Normal — 128 kbps": 128,
    "Boa — 192 kbps": 192,
    "Alta — 256 kbps": 256,
    "Máxima — 320 kbps": 320,
}


@st.cache_data(show_spinner=False, max_entries=32)
def _info(dados: bytes) -> pt.InfoAudio | str:
    """Info da faixa de som, ou o motivo de não dar para converter."""
    try:
        return pt.info_audio(dados)
    except ValueError as erro:
        return str(erro)


def _receber_videos() -> list[tuple[str, bytes]]:
    enviados = st.file_uploader(
        "Escolha os vídeos (pode ser vários de uma vez)",
        type=pt.FORMATOS_VIDEO,
        accept_multiple_files=True,
        key="upload_mp3",
    )
    return [(arquivo.name, arquivo.getvalue()) for arquivo in enviados or []]


def _campo_tempo(alvo, rotulo: str, chave: str, placeholder: str) -> float | None:
    texto = alvo.text_input(rotulo, key=chave, placeholder=placeholder)
    try:
        return pt.ler_tempo(texto)
    except ValueError as erro:
        alvo.error(str(erro))
        return None


def tela_mp4_para_mp3() -> None:
    titulo(
        "🎵",
        "MP4 para MP3",
        "Tira o som de vídeos e salva como MP3. Funciona também com MOV, WEBM, MKV, AVI e M4A.",
    )

    arquivos = _receber_videos()
    if not arquivos:
        st.caption("Formatos aceitos: " + ", ".join(f.upper() for f in pt.FORMATOS_VIDEO) + ".")
        return

    infos = [_info(dados) for _, dados in arquivos]
    validos = [
        (nome, dados, info)
        for (nome, dados), info in zip(arquivos, infos)
        if isinstance(info, pt.InfoAudio)
    ]
    for (nome, _), info in zip(arquivos, infos):
        if isinstance(info, str):
            st.warning(f"{nome}: {info}. Fica de fora.")
    if not validos:
        return

    duracao_total = sum(info.duracao for *_, info in validos)
    if len(validos) == 1:
        nome, _, info = validos[0]
        canais = "mono" if info.canais == 1 else "estéreo"
        st.caption(
            f"**{nome}** — {pt.formatar_tempo(info.duracao)} de áudio, {canais}, "
            f"{info.taxa / 1000:g} kHz ({info.codec.upper()})."
        )
    else:
        st.caption(f"{len(validos)} vídeos, {pt.formatar_tempo(duracao_total)} de áudio no total.")

    st.subheader("Opções")
    colunas = st.columns([2, 1])
    bitrate = QUALIDADES[
        colunas[0].selectbox(
            "Qualidade",
            list(QUALIDADES),
            index=1,
            key="mp3_qualidade",
            help="192 kbps já soa igual ao original para quase todo mundo. "
                 "Para fala (aula, podcast), 128 kbps sobra.",
        )
    ]
    mono = colunas[1].checkbox(
        "Mono",
        key="mp3_mono",
        help="Junta os dois canais num só. Para fala, mono em 128 kbps soa melhor que "
             "estéreo em 128 kbps; em música perde a sensação de espaço.",
    )
    opcoes: dict = {"bitrate": bitrate, "mono": mono}

    duracao_saida = duracao_total
    if len(validos) == 1:
        with st.expander("Cortar um trecho (opcional)"):
            esquerda, direita = st.columns(2)
            inicio = _campo_tempo(esquerda, "Começa em", "mp3_inicio", "0:00")
            fim = _campo_tempo(
                direita, "Termina em", "mp3_fim", pt.formatar_tempo(validos[0][2].duracao)
            )
            st.caption("Use minutos:segundos (1:30) ou só segundos (90). Em branco = do começo / até o fim.")
        if inicio is not None:
            opcoes["inicio"] = inicio
        if fim is not None:
            opcoes["fim"] = fim
        comeco = inicio or 0.0
        final = min(fim, duracao_total) if fim is not None else duracao_total
        duracao_saida = max(0.0, final - comeco)

    estimativa = int(duracao_saida * bitrate * 1000 / 8)
    st.info(f"Tamanho estimado: {pt.tamanho_legivel(estimativa)}.")

    assinatura = "|".join(f"{nome}:{len(dados)}" for nome, dados, _ in validos)
    assinatura += repr(sorted(opcoes.items()))
    quantos = len(validos)
    rotulo = "Converter para MP3" if quantos == 1 else f"Converter {quantos} vídeos para MP3"

    if st.button(rotulo, type="primary", width="stretch"):
        barra = st.progress(0.0, text="Convertendo...")

        def rodar():
            prontos, problemas = pt.converter_lote(
                [(nome, dados) for nome, dados, _ in validos],
                progresso=lambda f: barra.progress(f, text="Convertendo..."),
                **opcoes,
            )
            if not prontos:
                raise ValueError("Nenhum vídeo pôde ser convertido: " + "; ".join(problemas))
            total = sum(len(conteudo) for _, conteudo in prontos)
            resumo = f"{len(prontos)} MP3 pronto(s), {pt.tamanho_legivel(total)} no total."
            if problemas:
                resumo += " Ficaram de fora: " + "; ".join(problemas) + "."
            return prontos, resumo

        with st.spinner("Convertendo..."):
            executar("mp3", assinatura, rodar)
        barra.empty()

    mostrar_resultado("mp3", assinatura, nome_do_zip="audios-mp3.zip", previa=False)

    guardado = st.session_state.get("resultado_mp3")
    if guardado and guardado["assinatura"] == assinatura and guardado["arquivos"]:
        nome, dados = guardado["arquivos"][0]
        st.caption(f"Ouvir antes de baixar — {nome}")
        st.audio(dados, format="audio/mpeg")
