"""Tela de download de vídeos do YouTube."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import executar, mostrar_resultado, titulo

_MB = 1024 * 1024


def _cookies() -> str | None:
    """Conteúdo de um cookies.txt guardado em [youtube] nos secrets, se houver."""
    try:
        bloco = st.secrets.get("youtube")
    except Exception:  # sem secrets.toml o Streamlit levanta erro ao ler
        return None
    if not bloco or not str(bloco.get("cookies") or "").strip():
        return None
    return str(bloco["cookies"])


# Os links de download do YouTube valem por algumas horas; 10 minutos de
# cache evitam perguntar de novo a cada clique sem servir link vencido.
@st.cache_data(ttl=600, show_spinner=False, max_entries=16)
def _ler(link: str, cookies: str | None) -> pt.youtube.Video:
    return pt.ler_video(link, cookies=cookies)


def _duracao(segundos: int) -> str:
    horas, resto = divmod(int(segundos), 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{segundos:02d}" if horas else f"{minutos}:{segundos:02d}"


def _tamanho(opcao: pt.youtube.Opcao) -> str:
    if not opcao.bytes:
        return "tamanho desconhecido"
    texto = pt.tamanho_legivel(int(opcao.bytes))
    return ("~" + texto) if opcao.aprox else texto


def _rotulo(opcao: pt.youtube.Opcao) -> str:
    partes = [opcao.rotulo]
    if opcao.fps:
        partes.append(f"{opcao.fps} fps")
    if not opcao.so_audio:
        partes.append(opcao.codec)
    partes.append(_tamanho(opcao))
    return " · ".join(partes)


def _cabe(opcao: pt.youtube.Opcao) -> bool:
    # Estimativa por bitrate erra alguns %, então só esconde o que passa com folga.
    folga = 1.0 if not opcao.aprox else 1.1
    return not opcao.bytes or opcao.bytes <= pt.LIMITE_YOUTUBE * folga


def _mostrar_video(video: pt.youtube.Video) -> None:
    if video.miniatura:
        colunas = st.columns([1, 2])
        colunas[0].image(video.miniatura, width="stretch")
        alvo = colunas[1]
    else:
        alvo = st.container()
    with alvo:
        st.markdown(f"**{video.titulo}**")
        detalhes = []
        if video.canal:
            detalhes.append(video.canal)
        if video.duracao:
            detalhes.append(_duracao(video.duracao))
        detalhes.append(f"[abrir no YouTube]({video.link})")
        st.markdown(" · ".join(detalhes))


def tela_youtube() -> None:
    cookies = _cookies()
    _corpo(cookies)
    _rodape(cookies)


def _corpo(cookies: str | None) -> None:
    titulo(
        "▶️",
        "Baixar do YouTube",
        "Cole o link de um vídeo, escolha a qualidade vendo o tamanho estimado e baixe "
        "em MP4 — ou só o áudio.",
    )

    with st.form("yt_form", border=False):
        link = st.text_input(
            "Link do vídeo",
            key="yt_link",
            placeholder="https://www.youtube.com/watch?v=...  ou  https://youtu.be/...",
            help="No app do YouTube: toque em **Compartilhar** e depois em **Copiar link**. "
                 "Shorts também valem.",
        )
        buscar = st.form_submit_button("Buscar vídeo", type="primary", width="stretch")

    # O vídeo e o resultado guardados só aparecem enquanto o link for o mesmo vídeo.
    try:
        video_id = pt.extrair_id(link)
    except pt.ErroYoutube:
        video_id = link.strip()

    if buscar:
        try:
            with st.spinner("Falando com o YouTube..."):
                st.session_state["yt_video"] = _ler(link, cookies)
        except pt.ErroYoutube as erro:
            st.session_state.pop("yt_video", None)
            st.error(str(erro))
        except Exception as erro:  # rede de segurança: o app não pode quebrar na cara
            st.session_state.pop("yt_video", None)
            st.error(f"Não consegui ler o vídeo: {erro}")

    video: pt.youtube.Video | None = st.session_state.get("yt_video")
    if not video or video.id != video_id:
        return

    _mostrar_video(video)

    cabem = [opcao for opcao in video.opcoes if _cabe(opcao)]
    fora = len(video.opcoes) - len(cabem)
    if not cabem:
        st.error(
            f"Todas as qualidades passam de {pt.LIMITE_YOUTUBE // _MB} MB, o limite do "
            "servidor. Vídeo longo demais para baixar por aqui."
        )
        return

    padrao = pt.escolher_opcao(cabem, 1080)
    escolha = st.radio(
        "Qualidade",
        options=range(len(cabem)),
        index=cabem.index(padrao) if padrao in cabem else 0,
        format_func=lambda i: _rotulo(cabem[i]),
        key=f"yt_qualidade_{video.id}",
        help="~ = estimativa pelo bitrate; o tamanho real pode variar alguns %.",
    )
    opcao = cabem[escolha]
    if fora:
        st.caption(
            f"{fora} qualidade(s) maior(es) ficaram de fora por passarem de "
            f"{pt.LIMITE_YOUTUBE // _MB} MB, o limite do servidor."
        )
    if not pt.youtube.ferramentas()[0]:
        st.caption("Sem ffmpeg no servidor, só aparecem os formatos que já vêm com som (até ~360p).")

    assinatura = f"{video.id}:{opcao.seletor}:{opcao.mp3}"
    if st.button("Baixar", type="primary", width="stretch", key="yt_baixar"):
        barra = st.progress(0.0, text="Começando o download...")

        def rodar():
            arquivo = pt.baixar_youtube(
                video, opcao, cookies=cookies,
                progresso=lambda fracao, texto: barra.progress(fracao, text=texto),
            )
            resumo = f"{opcao.rotulo}: {pt.tamanho_legivel(len(arquivo[1]))}"
            if opcao.bytes:
                resumo += f" (estimado: {_tamanho(opcao)})"
            return [arquivo], resumo + "."

        executar("yt", assinatura, rodar)
        barra.empty()

    mostrar_resultado("yt", assinatura, previa=False)


def _rodape(cookies: str | None) -> None:
    st.divider()
    st.caption(
        "Baixe só o que você tem direito de usar: o conteúdo continua sendo de quem publicou."
    )
    with st.expander("Por que às vezes não funciona?"):
        st.markdown(
            f"""
            - **O YouTube desconfia de servidores.** O app roda num servidor na
              nuvem, e o YouTube às vezes pede para "provar que não é um robô".
              Quando acontecer, espere uns minutos e tente de novo.
            - **Vídeos privados, só para membros ou com restrição de idade**
              precisam de login.
            - **Ao vivo** só depois que a transmissão termina.
            - **Limite de tamanho:** {pt.LIMITE_YOUTUBE // _MB} MB por arquivo,
              pela memória do servidor. Vídeo longo em 1080p passa fácil disso;
              escolha 720p ou menos, ou só o áudio.
            - **O YouTube mudou algo?** O downloader (yt-dlp) precisa de
              atualização frequente. Reinicie o app no Streamlit Cloud para ele
              reinstalar a versão mais nova.

            Para passar pelo "não sou um robô" e pela restrição de idade, dá para
            usar cookies de uma conta logada. Exporte os cookies do youtube.com
            no formato *Netscape* (`cookies.txt`, com uma extensão de navegador)
            e, no Streamlit Cloud, abra *Settings → Secrets* do app e cole:

            ```toml
            [youtube]
            cookies = \"\"\"
            # Netscape HTTP Cookie File
            .youtube.com	TRUE	/	TRUE	0	...
            \"\"\"
            ```

            Use uma **conta secundária**: quem tem esses cookies tem acesso à
            conta. Nunca coloque esses valores no código nem no GitHub.
            """
        )
        ffmpeg, runtimes = pt.youtube.ferramentas()
        st.caption(
            "Neste servidor: ffmpeg " + ("**sim**" if ffmpeg else "**não**")
            + " · runtime JS " + (f"**{next(iter(runtimes))}**" if runtimes else "**não**")
            + " · cookies " + ("**sim**." if cookies else "**não**.")
        )
