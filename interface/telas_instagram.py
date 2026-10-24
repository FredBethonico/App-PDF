"""Tela de download de fotos e vídeos do Instagram."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import executar, mostrar_resultado, titulo

_PREVIA_COLUNAS = 3
_SEM_PREVIA = (".heic", ".avif")  # o navegador não mostra; o download funciona


def _sessao() -> dict | None:
    """Cookies de login guardados em [instagram] nos secrets, se houver."""
    try:
        bloco = st.secrets.get("instagram")
    except Exception:  # sem secrets.toml o Streamlit levanta erro ao ler
        return None
    if not bloco or not bloco.get("sessionid"):
        return None
    return {chave: str(valor) for chave, valor in dict(bloco).items()}


# Os links da CDN do Instagram valem por algumas horas; 10 minutos de cache
# evitam bater de novo no Instagram a cada clique sem servir link vencido.
@st.cache_data(ttl=600, show_spinner=False, max_entries=16)
def _ler(link: str, sessao: dict | None) -> pt.instagram.Post:
    return pt.ler_post(link, sessao=sessao)


def _resumo(post, prontos: list, problemas: list[str]) -> str:
    partes = []
    if post.fotos:
        partes.append(f"{post.fotos} foto(s)")
    if post.videos:
        partes.append(f"{post.videos} vídeo(s)")
    total = sum(len(dados) for _, dados in prontos)
    resumo = f"Post de @{post.autor}: {' e '.join(partes)}, {pt.tamanho_legivel(total)} no total."
    if problemas:
        resumo += " Ficaram de fora: " + "; ".join(problemas) + "."
    return resumo


def _mostrar_post(guardado: dict) -> None:
    post = guardado["post"]
    arquivos = guardado["arquivos"]

    detalhes = f"**@{post.autor}**"
    if post.data:
        detalhes += f" · {post.data:%d/%m/%Y}"
    detalhes += f" · [abrir no Instagram](https://www.instagram.com/p/{post.shortcode}/)"
    st.markdown(detalhes)
    if post.legenda:
        with st.expander("Legenda"):
            st.text(post.legenda)

    with st.expander(f"Prévia ({len(arquivos)})", expanded=True):
        for faixa in range(0, len(arquivos), _PREVIA_COLUNAS):
            colunas = st.columns(_PREVIA_COLUNAS)
            for coluna, (nome, dados) in zip(colunas, arquivos[faixa : faixa + _PREVIA_COLUNAS]):
                if nome.endswith(".mp4"):
                    coluna.video(dados, format="video/mp4")
                    coluna.caption(nome)
                elif nome.endswith(_SEM_PREVIA):
                    coluna.caption(f"{nome} — sem prévia no navegador, mas baixa normal.")
                else:
                    coluna.image(dados, caption=nome, width="stretch")


def tela_instagram() -> None:
    titulo(
        "📸",
        "Baixar do Instagram",
        "Cole o link de um post, reel ou carrossel público e baixe as fotos e vídeos.",
    )

    sessao = _sessao()
    with st.form("insta_form", border=False):
        link = st.text_input(
            "Link do post",
            key="insta_link",
            placeholder="https://www.instagram.com/p/...  ou  .../reel/...",
            help="No app do Instagram: toque nos três pontinhos (ou no avião de "
                 "papel) do post e escolha **Copiar link**.",
        )
        buscar = st.form_submit_button("Buscar e baixar", type="primary", width="stretch")

    # O resultado guardado só aparece enquanto o link na caixa for o mesmo post.
    try:
        assinatura = pt.extrair_shortcode(link)
    except pt.ErroInstagram:
        assinatura = link.strip()

    if buscar:
        barra = st.progress(0.0, text="Buscando o post...")

        def rodar():
            post = _ler(link, sessao)
            prontos, problemas = pt.baixar_midias(
                post, progresso=lambda f: barra.progress(f, text="Baixando as mídias...")
            )
            if not prontos:
                raise ValueError("Não consegui baixar nada: " + "; ".join(problemas))
            st.session_state["insta_post"] = {
                "assinatura": assinatura,
                "post": post,
                "arquivos": prontos,
            }
            return prontos, _resumo(post, prontos, problemas)

        with st.spinner("Falando com o Instagram..."):
            executar("insta", assinatura, rodar)
        barra.empty()

    guardado = st.session_state.get("insta_post")
    if guardado and guardado["assinatura"] == assinatura:
        post = guardado["post"]
        mostrar_resultado(
            "insta", assinatura, nome_do_zip=f"{post.autor}-{post.shortcode}.zip", previa=False
        )
        _mostrar_post(guardado)

    st.divider()
    st.caption(
        "Baixe só o que você tem direito de usar: o conteúdo continua sendo de quem publicou."
    )
    with st.expander("Por que às vezes não funciona?"):
        st.markdown(
            f"""
            - **Só posts públicos.** Conta privada e stories precisam de login.
            - **O Instagram limita servidores.** O app roda num servidor na
              nuvem, e o Instagram costuma recusar pedidos sem login vindos
              desses endereços. Quando acontecer, espere uns minutos e tente
              de novo.
            - **Limite de tamanho:** {pt.LIMITE_POR_ARQUIVO // (1024 * 1024)} MB por arquivo,
              pela memória do servidor.

            Para ficar mais estável, dá para usar uma sessão logada. No Streamlit
            Cloud, abra *Settings → Secrets* do app e cole:

            ```toml
            [instagram]
            sessionid = "valor do cookie sessionid"
            csrftoken = "valor do cookie csrftoken"   # opcional
            ds_user_id = "valor do cookie ds_user_id" # opcional
            ```

            Os valores saem dos cookies do instagram.com no navegador, com a conta
            logada. Use uma **conta secundária**: quem tem o `sessionid` tem
            acesso à conta, e o Instagram pode bloquear contas usadas assim.
            Nunca coloque esses valores no código nem no GitHub.
            """
        )
        st.caption(
            "Sessão logada configurada neste app: " + ("**sim**." if sessao else "**não**.")
        )
