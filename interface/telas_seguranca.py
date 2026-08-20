"""Telas de senha, permissões e diagnóstico do arquivo."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import executar, mostrar_resultado, previa_pdf, receber_pdf, titulo


# --------------------------------------------------------------------------


def tela_desbloquear() -> None:
    titulo("🔓", "Desbloquear PDF", "Tira a senha e as travas de impressão e cópia.")

    st.caption(
        "Use nos seus próprios arquivos — os que você recebeu do banco, da gráfica "
        "ou de um sistema que trava a impressão sem motivo."
    )

    entrada = receber_pdf("desbloquear")
    if entrada is None:
        return

    if not entrada.info.criptografado:
        st.success("Este PDF já está livre: não tem senha nem restrições.")
        st.caption("Nada a fazer aqui. Pode usar direto nas outras ferramentas.")
        return

    bloqueado = [nome for nome, ok in entrada.info.permissoes.items() if not ok]
    if bloqueado:
        st.warning("Restrições ativas: " + ", ".join(bloqueado).lower() + ".")
    else:
        st.info("O arquivo é criptografado, mas não bloqueia nenhuma ação.")

    if st.button("Desbloquear", type="primary", width="stretch"):
        def rodar():
            dados = pt.desbloquear(entrada.dados, entrada.senha)
            return (
                [(pt.sufixar(entrada.nome, "desbloqueado"), dados)],
                "Senha e restrições removidas.",
            )

        with st.spinner("Desbloqueando..."):
            executar("desbloquear", entrada.assinatura, rodar)

    mostrar_resultado("desbloquear", entrada.assinatura)


# --------------------------------------------------------------------------


def tela_proteger() -> None:
    titulo("🔒", "Proteger PDF", "Coloque senha e escolha o que os outros podem fazer.")

    entrada = receber_pdf("proteger")
    if entrada is None:
        return

    st.subheader("Senhas")
    colunas = st.columns(2)
    senha_abertura = colunas[0].text_input(
        "Senha para abrir", type="password", key="prot_abertura",
        help="Sem ela ninguém lê o arquivo. Deixe em branco para que qualquer "
             "um leia, mas com as restrições abaixo valendo.",
    )
    senha_dono = colunas[1].text_input(
        "Senha de dono (opcional)", type="password", key="prot_dono",
        help="É a que libera as restrições. Se ficar em branco, a senha de "
             "abertura faz os dois papéis.",
    )

    st.subheader("O que fica liberado")
    colunas = st.columns(2)
    imprimir = colunas[0].checkbox("Imprimir", value=True)
    copiar = colunas[0].checkbox("Copiar texto e imagens", value=True)
    editar = colunas[1].checkbox("Editar o conteúdo", value=False)
    anotar = colunas[1].checkbox("Comentar e preencher formulários", value=True)

    if senha_abertura:
        confere = st.text_input(
            "Repita a senha de abertura", type="password", key="prot_confere"
        )
        if confere and confere != senha_abertura:
            st.error("As senhas não são iguais.")

    st.warning(
        "Anote a senha em lugar seguro. Sem ela não há como abrir o arquivo depois — "
        "nem por aqui.",
        icon="⚠️",
    )

    pronto = bool(senha_abertura or senha_dono)
    if senha_abertura and st.session_state.get("prot_confere") != senha_abertura:
        pronto = False

    if st.button("Proteger", type="primary", width="stretch", disabled=not pronto):
        def rodar():
            dados = pt.proteger(
                entrada.dados,
                senha_abertura=senha_abertura,
                senha_dono=senha_dono,
                permitir_impressao=imprimir,
                permitir_copia=copiar,
                permitir_edicao=editar,
                permitir_anotacoes=anotar,
                senha_atual=entrada.senha,
            )
            travas = [
                nome for nome, ok in {
                    "impressão": imprimir, "cópia": copiar,
                    "edição": editar, "comentários": anotar,
                }.items() if not ok
            ]
            resumo = "Protegido com AES-256."
            if senha_abertura:
                resumo += " Pede senha para abrir."
            if travas:
                resumo += " Bloqueado: " + ", ".join(travas) + "."
            return [(pt.sufixar(entrada.nome, "protegido"), dados)], resumo

        with st.spinner("Protegendo..."):
            executar("proteger", entrada.assinatura, rodar)

    if not pronto:
        st.caption("Preencha e confirme a senha para liberar o botão.")

    mostrar_resultado("proteger", entrada.assinatura, previa=False)


# --------------------------------------------------------------------------


def tela_informacoes() -> None:
    titulo("ℹ️", "Informações do PDF", "Veja o que tem dentro do arquivo antes de mexer nele.")

    entrada = receber_pdf("info")
    if entrada is None:
        return

    info = entrada.info

    st.subheader("Documento")
    linhas = {
        "Título": info.titulo or "—",
        "Autor": info.autor or "—",
        "Criado com": info.criador or "—",
        "Gerado por": info.produtor or "—",
        "Versão do PDF": info.versao,
        "Criptografado": "sim" if info.criptografado else "não",
    }
    for rotulo, valor in linhas.items():
        colunas = st.columns([1, 3])
        colunas[0].caption(rotulo)
        colunas[1].write(valor)

    if info.permissoes:
        st.subheader("Permissões")
        colunas = st.columns(len(info.permissoes))
        for coluna, (nome, liberado) in zip(colunas, info.permissoes.items()):
            coluna.metric(nome, "liberado" if liberado else "bloqueado")

    st.subheader("Páginas")
    if info.paginas_iguais:
        st.write(f"{info.paginas} página(s), todas em {info.descricao_pagina(0)}.")
    else:
        st.write(f"{info.paginas} página(s), com tamanhos diferentes:")
        agrupado: dict[str, list[int]] = {}
        for indice in range(info.paginas):
            agrupado.setdefault(info.descricao_pagina(indice), []).append(indice)
        for descricao, indices in agrupado.items():
            st.caption(f"• {descricao} — páginas {pt.formatar_intervalo(indices)}")

    with st.spinner("Analisando o conteúdo..."):
        diag = pt.diagnostico(entrada.dados, entrada.senha)
        _, vazias = pt.extrair_texto(entrada.dados, senha=entrada.senha)

    st.subheader("Conteúdo")
    colunas = st.columns(3)
    colunas[0].metric("Imagens embutidas", diag["imagens"])
    colunas[1].metric("Peso das imagens", f"{diag['fracao_imagem']:.0%}")
    colunas[2].metric("Páginas sem texto", f"{vazias} de {info.paginas}")

    if vazias == info.paginas and info.paginas:
        st.info(
            "Nenhuma página tem camada de texto: este PDF é uma digitalização ou "
            "foi todo rasterizado. Não dá para buscar nem copiar o conteúdo escrito.",
            icon="🔍",
        )
    if diag["fracao_imagem"] > 0.6:
        st.info(
            "As imagens dominam o arquivo — a ferramenta **Comprimir** deve dar um "
            "bom resultado aqui.",
            icon="🪶",
        )

    st.subheader("Prévia")
    previa_pdf(entrada.dados, paginas=4, largura=240)
