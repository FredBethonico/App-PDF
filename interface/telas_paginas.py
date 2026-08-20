"""Telas que mexem na ordem, na quantidade e no giro das páginas."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import (
    campo_intervalo,
    executar,
    limpar_resultado,
    miniaturas_png,
    mostrar_resultado,
    receber_pdf,
    receber_varios_pdfs,
    resumo_de_tamanho,
    titulo,
)

POR_LINHA = 6
POR_TELA = 24


# --------------------------------------------------------------------------


def tela_juntar() -> None:
    titulo("🔗", "Juntar PDFs", "Vários arquivos viram um só, na ordem que você definir.")

    arquivos = receber_varios_pdfs("juntar", "Escolha dois ou mais PDFs")
    if len(arquivos) < 2:
        if arquivos:
            st.info("Falta pelo menos mais um arquivo.")
        return

    nomes = [nome for nome, _ in arquivos]
    # Trocar os arquivos enviados reinicia a ordem manual.
    if st.session_state.get("juntar_nomes") != nomes:
        st.session_state["juntar_nomes"] = nomes
        st.session_state["juntar_ordem"] = list(range(len(arquivos)))
        limpar_resultado("juntar")
    ordem: list[int] = st.session_state["juntar_ordem"]

    st.subheader("Ordem")
    st.caption("Use as setas para mudar a sequência das partes.")
    for posicao, indice in enumerate(list(ordem)):
        nome, dados = arquivos[indice]
        try:
            n_paginas = pt.contar_paginas(dados)
            detalhe = f"{n_paginas} pág. · {pt.tamanho_legivel(len(dados))}"
        except Exception:
            detalhe = "não consegui ler este arquivo"

        colunas = st.columns([0.6, 5, 2, 0.8, 0.8])
        colunas[0].markdown(f"**{posicao + 1}.**")
        colunas[1].write(nome)
        colunas[2].caption(detalhe)
        if colunas[3].button("↑", key=f"sobe_{posicao}", disabled=posicao == 0,
                             width="stretch"):
            ordem[posicao - 1], ordem[posicao] = ordem[posicao], ordem[posicao - 1]
            st.rerun()
        if colunas[4].button("↓", key=f"desce_{posicao}",
                             disabled=posicao == len(ordem) - 1,
                             width="stretch"):
            ordem[posicao + 1], ordem[posicao] = ordem[posicao], ordem[posicao + 1]
            st.rerun()

    colunas = st.columns(2)
    if colunas[0].button("Ordem alfabética", width="stretch"):
        st.session_state["juntar_ordem"] = sorted(ordem, key=lambda i: nomes[i].lower())
        st.rerun()
    if colunas[1].button("Inverter", width="stretch"):
        st.session_state["juntar_ordem"] = list(reversed(ordem))
        st.rerun()

    com_indice = st.checkbox(
        "Criar marcadores com o nome de cada arquivo",
        value=True,
        help="Vira o índice lateral do leitor de PDF, útil em apostilas.",
    )
    nome_saida = st.text_input("Nome do arquivo final", value="documento-unido.pdf")

    # A ordem entra na assinatura para que reordenar invalide o resultado antigo.
    assinatura = "|".join(nomes) + str(ordem)
    if st.button("Juntar", type="primary", width="stretch"):
        selecionados = [arquivos[i] for i in ordem]
        total_antes = sum(len(d) for _, d in selecionados)

        def rodar():
            resultado = pt.juntar(selecionados, com_indice=com_indice)
            paginas = pt.contar_paginas(resultado)
            return (
                [(pt.nome_seguro(nome_saida or "documento-unido.pdf"), resultado)],
                f"{len(selecionados)} arquivos, {paginas} páginas. "
                + resumo_de_tamanho(total_antes, len(resultado)),
            )

        with st.spinner("Juntando..."):
            executar("juntar", assinatura, rodar)

    mostrar_resultado("juntar", assinatura)


# --------------------------------------------------------------------------


def tela_extrair() -> None:
    titulo("✂️", "Extrair ou remover páginas",
           "Guarde só o pedaço que interessa — ou jogue fora o que não interessa.")

    entrada = receber_pdf("extrair")
    if entrada is None:
        return

    modo = st.radio(
        "O que fazer",
        ["Ficar só com estas páginas", "Remover estas páginas"],
        horizontal=True,
        key="modo_extrair",
    )
    intervalo = campo_intervalo("extrair", entrada.paginas, "Páginas")

    if intervalo.strip():
        try:
            escolhidas = pt.parse_intervalo(intervalo, entrada.paginas)
        except pt.ErroDeIntervalo as erro:
            st.error(str(erro))
            escolhidas = []
        if escolhidas:
            if modo.startswith("Ficar"):
                st.caption(
                    f"Resultado: {len(escolhidas)} página(s) — "
                    f"{pt.formatar_intervalo(escolhidas)}."
                )
            else:
                restantes = [i for i in range(entrada.paginas) if i not in set(escolhidas)]
                st.caption(
                    f"Resultado: {len(restantes)} página(s) — "
                    f"{pt.formatar_intervalo(restantes) or 'nenhuma'}."
                )
            _mostrar_previa(entrada, escolhidas[:6])

    if st.button("Gerar PDF", type="primary", width="stretch"):
        def rodar():
            if modo.startswith("Ficar"):
                dados = pt.extrair(entrada.dados, intervalo, entrada.senha)
                sufixo = "paginas"
            else:
                dados = pt.remover(entrada.dados, intervalo, entrada.senha)
                sufixo = "sem-paginas"
            paginas = pt.contar_paginas(dados)
            return (
                [(pt.sufixar(entrada.nome, sufixo), dados)],
                f"{paginas} página(s). " + resumo_de_tamanho(entrada.info.tamanho, len(dados)),
            )

        with st.spinner("Recortando..."):
            executar("extrair", entrada.assinatura, rodar)

    mostrar_resultado("extrair", entrada.assinatura)


def _mostrar_previa(entrada, indices: list[int]) -> None:
    if not indices:
        return
    with st.expander("Conferir as páginas escolhidas", expanded=False):
        imagens = miniaturas_png(entrada.dados, tuple(indices), 200, entrada.senha)
        for coluna, (indice, imagem) in zip(st.columns(len(imagens)), zip(indices, imagens)):
            coluna.image(imagem, caption=f"Página {indice + 1}", width="stretch")


# --------------------------------------------------------------------------


def tela_dividir() -> None:
    titulo("🗂️", "Dividir PDF", "Um arquivo grande vira vários menores, prontos em um .zip.")

    entrada = receber_pdf("dividir")
    if entrada is None:
        return

    modo = st.radio(
        "Como dividir",
        ["A cada N páginas", "Em N arquivos iguais", "Por intervalos que eu escolher"],
        key="modo_dividir",
    )

    if modo == "A cada N páginas":
        quantidade = st.number_input(
            "Páginas por arquivo", min_value=1, max_value=max(entrada.paginas, 1),
            value=min(10, entrada.paginas), step=1,
        )
        previsao = -(-entrada.paginas // quantidade)
        st.caption(f"Vai gerar {previsao} arquivo(s).")
        acao = lambda: pt.dividir_em_blocos(
            entrada.dados, int(quantidade), entrada.nome, entrada.senha
        )

    elif modo == "Em N arquivos iguais":
        quantidade = st.number_input(
            "Quantidade de arquivos", min_value=1, max_value=max(entrada.paginas, 1),
            value=min(2, entrada.paginas), step=1,
        )
        por_parte, resto = divmod(entrada.paginas, int(quantidade))
        st.caption(
            f"Cada arquivo fica com {por_parte} página(s)"
            + (f", e os {resto} primeiros ganham uma a mais." if resto else ".")
        )
        acao = lambda: pt.dividir_em_partes(
            entrada.dados, int(quantidade), entrada.nome, entrada.senha
        )

    else:
        texto = st.text_area(
            "Um intervalo por linha",
            value="1-5\n6-10",
            height=140,
            help="Cada linha vira um arquivo. Aceita a mesma sintaxe de sempre: 1-5, 8, 12-",
        )
        linhas = [linha for linha in texto.splitlines() if linha.strip()]
        st.caption(f"Vai gerar {len(linhas)} arquivo(s).")
        acao = lambda: pt.dividir_por_intervalos(
            entrada.dados, linhas, entrada.nome, entrada.senha
        )

    if st.button("Dividir", type="primary", width="stretch"):
        def rodar():
            partes = acao()
            total = sum(len(d) for _, d in partes)
            return partes, f"{len(partes)} arquivo(s), {pt.tamanho_legivel(total)} no total."

        with st.spinner("Dividindo..."):
            executar("dividir", entrada.assinatura, rodar)

    mostrar_resultado(
        "dividir", entrada.assinatura,
        nome_do_zip=f"{pt.nome_base(entrada.nome)}-dividido.zip",
    )


# --------------------------------------------------------------------------


def tela_organizar() -> None:
    titulo("🔄", "Organizar páginas",
           "Veja as páginas, gire as tortas, remova as que sobraram e mude a ordem.")

    entrada = receber_pdf("organizar")
    if entrada is None:
        return

    estado = _estado_organizar(entrada)

    st.subheader("Ações rápidas")
    colunas = st.columns(4)
    if colunas[0].button("↻ Girar tudo 90°", width="stretch"):
        for indice in estado["ordem"]:
            estado["giros"][indice] = (estado["giros"].get(indice, 0) + 90) % 360
        st.rerun()
    if colunas[1].button("↺ Girar tudo -90°", width="stretch"):
        for indice in estado["ordem"]:
            estado["giros"][indice] = (estado["giros"].get(indice, 0) - 90) % 360
        st.rerun()
    if colunas[2].button("⇅ Inverter ordem", width="stretch"):
        estado["ordem"] = list(reversed(estado["ordem"]))
        st.rerun()
    if colunas[3].button("⟲ Recomeçar", width="stretch"):
        st.session_state.pop("organizar_estado", None)
        limpar_resultado("organizar")
        st.rerun()

    with st.expander("Reordenar digitando (avançado)"):
        atual = pt.formatar_intervalo(estado["ordem"])
        nova = st.text_input(
            "Nova ordem das páginas", value=atual,
            help="Use os números da numeração original. Ex.: 3,1,2,5-9",
        )
        if st.button("Aplicar ordem"):
            try:
                pedida = pt.parse_intervalo(nova, entrada.paginas)
                # dict.fromkeys tira repetidas mantendo a ordem digitada
                estado["ordem"] = list(dict.fromkeys(pedida))
                st.rerun()
            except pt.ErroDeIntervalo as erro:
                st.error(str(erro))

    _grade_de_paginas(entrada, estado)

    st.divider()
    removidas = entrada.paginas - len(estado["ordem"])
    giradas = sum(1 for g in estado["giros"].values() if g % 360)
    st.write(
        f"**{len(estado['ordem'])} página(s)** no resultado"
        + (f" · {removidas} removida(s)" if removidas else "")
        + (f" · {giradas} girada(s)" if giradas else "")
    )

    if st.button("Gerar PDF organizado", type="primary", width="stretch"):
        def rodar():
            dados = pt.organizar(
                entrada.dados, list(estado["ordem"]), dict(estado["giros"]), entrada.senha
            )
            return (
                [(pt.sufixar(entrada.nome, "organizado"), dados)],
                f"{pt.contar_paginas(dados)} página(s). "
                + resumo_de_tamanho(entrada.info.tamanho, len(dados)),
            )

        with st.spinner("Montando..."):
            executar("organizar", entrada.assinatura, rodar)

    mostrar_resultado("organizar", entrada.assinatura)


def _estado_organizar(entrada) -> dict:
    """Ordem e giros ficam na sessão; trocar de arquivo zera tudo."""
    estado = st.session_state.get("organizar_estado")
    if not estado or estado.get("assinatura") != entrada.assinatura:
        estado = {
            "assinatura": entrada.assinatura,
            "ordem": list(range(entrada.paginas)),
            "giros": {},
        }
        st.session_state["organizar_estado"] = estado
        limpar_resultado("organizar")
    return estado


def _grade_de_paginas(entrada, estado: dict) -> None:
    ordem: list[int] = estado["ordem"]
    if not ordem:
        st.warning("Você removeu todas as páginas. Use **Recomeçar** para voltar.")
        return

    inicio = 0
    if len(ordem) > POR_TELA:
        total_telas = -(-len(ordem) // POR_TELA)
        # Remover páginas encolhe a lista: sem esse ajuste o slider guardaria
        # um bloco que não existe mais e o Streamlit levantaria erro.
        atual = min(st.session_state.get("organizar_tela", 1), total_telas)
        st.session_state["organizar_tela"] = atual
        tela = st.select_slider(
            "Bloco de páginas",
            options=list(range(1, total_telas + 1)),
            format_func=lambda t: f"{(t - 1) * POR_TELA + 1}–{min(t * POR_TELA, len(ordem))}",
            key="organizar_tela",
        )
        inicio = (tela - 1) * POR_TELA

    visiveis = ordem[inicio : inicio + POR_TELA]
    imagens = miniaturas_png(entrada.dados, tuple(visiveis), 200, entrada.senha)

    for deslocamento in range(0, len(visiveis), POR_LINHA):
        bloco = list(enumerate(visiveis))[deslocamento : deslocamento + POR_LINHA]
        colunas = st.columns(POR_LINHA)
        for coluna, (posicao_local, indice) in zip(colunas, bloco):
            giro = estado["giros"].get(indice, 0) % 360
            with coluna:
                st.image(imagens[posicao_local], width="stretch")
                st.caption(
                    f"#{inicio + posicao_local + 1} · original {indice + 1}"
                    + (f" · {giro}°" if giro else "")
                )
                botoes = st.columns(3)
                if botoes[0].button("↺", key=f"esq_{indice}", help="Girar -90°",
                                    width="stretch"):
                    estado["giros"][indice] = (giro - 90) % 360
                    st.rerun()
                if botoes[1].button("↻", key=f"dir_{indice}", help="Girar +90°",
                                    width="stretch"):
                    estado["giros"][indice] = (giro + 90) % 360
                    st.rerun()
                if botoes[2].button("✕", key=f"rem_{indice}", help="Remover página",
                                    width="stretch"):
                    estado["ordem"] = [i for i in ordem if i != indice]
                    estado["giros"].pop(indice, None)
                    st.rerun()
