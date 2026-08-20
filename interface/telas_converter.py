"""Telas de compressão, conversão entre PDF e imagem, e extração de texto."""

from __future__ import annotations

import streamlit as st

import pdf_tools as pt

from .comum import (
    _camada_de_texto,
    _diagnostico,
    campo_intervalo,
    executar,
    mostrar_resultado,
    receber_imagens,
    receber_pdf,
    resumo_de_tamanho,
    titulo,
)


# --------------------------------------------------------------------------


def tela_comprimir() -> None:
    titulo("🪶", "Comprimir PDF", "Deixe o arquivo leve o bastante para caber num e-mail.")

    entrada = receber_pdf("comprimir")
    if entrada is None:
        return

    with st.spinner("Analisando o arquivo..."):
        diag = _diagnostico(entrada.dados, entrada.senha)

    if diag["imagens"]:
        st.info(
            f"Encontrei {diag['imagens']} imagem(ns) ocupando cerca de "
            f"{diag['fracao_imagem']:.0%} do arquivo "
            f"({pt.tamanho_legivel(diag['bytes_imagem'])})."
        )
    else:
        st.info("Este PDF é praticamente todo texto e vetor — não há fotos para encolher.")

    modos = {
        "Sem perder nada": (
            "estrutura",
            "Só reempacota o arquivo. O visual fica **idêntico**. "
            "Ganho pequeno na maioria dos casos, grande em PDFs de Word e scanners antigos.",
        ),
        "Recomprimir imagens": (
            "imagens",
            "Reduz a resolução e a qualidade das fotos, mas **o texto continua texto**: "
            "dá para selecionar, copiar e buscar. É a melhor escolha na maior parte das vezes.",
        ),
        "Transformar tudo em imagem": (
            "raster",
            "Fotografa cada página. Encolhe muito, mas **o texto deixa de ser selecionável** "
            "e a busca para de funcionar. Use como último recurso.",
        ),
    }
    padrao = {"estrutura": 0, "imagens": 1}.get(diag["sugestao"], 1)
    if not diag["imagens"]:
        padrao = 0

    escolha = st.radio("Modo", list(modos), index=padrao, key="modo_comprimir")
    chave_modo, explicacao = modos[escolha]
    st.caption(explicacao)

    opcoes: dict = {}
    if chave_modo == "imagens":
        nivel = st.select_slider(
            "Intensidade", options=list(pt.NIVEIS), value="Equilibrado"
        )
        opcoes = dict(pt.NIVEIS[nivel])
        with st.expander("Ajuste fino"):
            opcoes["qualidade"] = st.slider(
                "Qualidade das imagens", 30, 95, opcoes["qualidade"],
                help="Abaixo de 50 começam a aparecer manchas em fotos.",
            )
            opcoes["lado_maximo"] = st.slider(
                "Resolução máxima (pixels no maior lado)", 600, 4000,
                opcoes["lado_maximo"], step=100,
                help="1600 px já imprime bem em A4. Para tela, 1200 basta.",
            )
    elif chave_modo == "raster":
        palavras, sem_texto = _camada_de_texto(entrada.dados, entrada.senha)
        com_texto = entrada.paginas - sem_texto
        if palavras > 50:
            st.warning(
                f"Este PDF tem **{palavras} palavras** de texto de verdade em "
                f"{com_texto} página(s). Rasterizar apaga tudo isso: o arquivo "
                "vira só imagem e ninguém mais consegue buscar nem copiar nada. "
                "Se o texto importa, volte para **Recomprimir imagens**.",
                icon="⚠️",
            )
        opcoes["dpi"] = st.slider(
            "Resolução (DPI)", 72, 300, 120, step=6,
            help="96–120 para ler na tela, 150–200 para imprimir.",
        )
        opcoes["qualidade"] = st.slider("Qualidade do JPEG", 30, 95, 70)
        opcoes["cinza"] = st.checkbox(
            "Converter para preto e branco",
            help="Corta mais um bom pedaço do tamanho em documentos digitalizados.",
        )

    if st.button("Comprimir", type="primary", width="stretch"):
        barra = st.progress(0.0, text="Processando...")

        def rodar():
            if chave_modo == "estrutura":
                dados = pt.comprimir_estrutura(entrada.dados, entrada.senha)
                detalhe = ""
            elif chave_modo == "imagens":
                dados, trocadas = pt.comprimir_imagens(
                    entrada.dados, senha=entrada.senha,
                    progresso=lambda f: barra.progress(f, text="Recomprimindo imagens..."),
                    **opcoes,
                )
                detalhe = (
                    f"{trocadas} imagem(ns) recomprimida(s). "
                    if trocadas
                    else "Nenhuma imagem valia a pena recomprimir. "
                )
            else:
                dados = pt.rasterizar(
                    entrada.dados, senha=entrada.senha,
                    progresso=lambda f: barra.progress(f, text="Rasterizando páginas..."),
                    **opcoes,
                )
                detalhe = "Texto não é mais selecionável. "
            return (
                [(pt.sufixar(entrada.nome, "comprimido"), dados)],
                detalhe + resumo_de_tamanho(entrada.info.tamanho, len(dados)),
            )

        with st.spinner("Comprimindo..."):
            executar("comprimir", entrada.assinatura, rodar)
        barra.empty()

    mostrar_resultado("comprimir", entrada.assinatura)


# --------------------------------------------------------------------------


def tela_pdf_para_imagens() -> None:
    titulo("🖼️", "PDF para imagens", "Cada página vira um arquivo de imagem.")

    entrada = receber_pdf("pdf2img")
    if entrada is None:
        return

    colunas = st.columns(3)
    formato = colunas[0].selectbox(
        "Formato", ["PNG", "JPEG", "WEBP"],
        help="PNG não perde qualidade. JPEG gera arquivos bem menores.",
    )
    dpi = colunas[1].slider(
        "Resolução (DPI)", 72, 600, 200, step=6,
        help="150 para tela, 300 para impressão, 600 para recorte e ampliação.",
    )
    qualidade = (
        colunas[2].slider("Qualidade", 40, 100, 90) if formato != "PNG" else 90
    )
    if formato == "PNG":
        colunas[2].caption("PNG não tem ajuste de qualidade.")

    intervalo = campo_intervalo("pdf2img", entrada.paginas)
    try:
        quantas = len(pt.parse_intervalo(intervalo, entrada.paginas))
    except pt.ErroDeIntervalo as erro:
        st.error(str(erro))
        return

    largura_px = int(entrada.info.tamanhos_pagina[0][0] / 72 * dpi) if entrada.info.tamanhos_pagina else 0
    st.caption(f"{quantas} imagem(ns), cerca de {largura_px} px de largura cada.")
    if quantas > 100:
        st.warning("São muitas páginas — isso pode levar um tempo bom.")

    if st.button("Converter", type="primary", width="stretch"):
        barra = st.progress(0.0, text="Renderizando...")

        def rodar():
            imagens = pt.pdf_para_imagens(
                entrada.dados, dpi=dpi, formato=formato, qualidade=qualidade,
                intervalo=intervalo, nome=entrada.nome, senha=entrada.senha,
                progresso=lambda f: barra.progress(f, text="Renderizando..."),
            )
            total = sum(len(d) for _, d in imagens)
            return imagens, f"{len(imagens)} imagem(ns), {pt.tamanho_legivel(total)} no total."

        with st.spinner("Convertendo..."):
            executar("pdf2img", entrada.assinatura, rodar)
        barra.empty()

    mostrar_resultado(
        "pdf2img", entrada.assinatura,
        nome_do_zip=f"{pt.nome_base(entrada.nome)}-imagens.zip",
        previa=False,
    )


# --------------------------------------------------------------------------


def tela_imagens_para_pdf() -> None:
    titulo("📄", "Imagens para PDF", "Fotos e prints viram um PDF, uma imagem por página.")

    arquivos = receber_imagens("img2pdf")
    if not arquivos:
        st.caption(
            "Formatos aceitos: " + ", ".join(f.upper() for f in pt.FORMATOS_ENTRADA) + "."
        )
        return

    nomes = [nome for nome, _ in arquivos]
    if st.session_state.get("img2pdf_nomes") != nomes:
        st.session_state["img2pdf_nomes"] = nomes
        st.session_state["img2pdf_ordem"] = sorted(
            range(len(arquivos)), key=lambda i: nomes[i].lower()
        )
    ordem: list[int] = st.session_state["img2pdf_ordem"]

    st.subheader(f"{len(arquivos)} imagem(ns)")
    colunas = st.columns(2)
    if colunas[0].button("Ordenar por nome", width="stretch"):
        st.session_state["img2pdf_ordem"] = sorted(ordem, key=lambda i: nomes[i].lower())
        st.rerun()
    if colunas[1].button("Inverter ordem", width="stretch"):
        st.session_state["img2pdf_ordem"] = list(reversed(ordem))
        st.rerun()

    grade = st.columns(6)
    for posicao, indice in enumerate(ordem[:12]):
        nome, dados = arquivos[indice]
        with grade[posicao % 6]:
            try:
                st.image(dados, width="stretch")
            except Exception:
                st.warning("não consegui abrir")
            st.caption(f"{posicao + 1}. {nome[:18]}")
    if len(ordem) > 12:
        st.caption(f"...e mais {len(ordem) - 12} imagem(ns).")

    st.subheader("Página")
    colunas = st.columns(3)
    tamanho = colunas[0].selectbox("Tamanho", pt.TAMANHOS_PAGINA)
    margem = colunas[1].slider("Margem (mm)", 0, 40, 0)
    recomprimir = colunas[2].checkbox(
        "Recomprimir como JPEG",
        help="Deixe desmarcado para preservar as imagens exatamente como estão.",
    )
    qualidade = st.slider("Qualidade do JPEG", 40, 95, 80) if recomprimir else None

    nome_saida = st.text_input("Nome do arquivo", value="imagens.pdf")
    assinatura = "|".join(nomes) + str(ordem)

    if st.button("Gerar PDF", type="primary", width="stretch"):
        selecionadas = [arquivos[i] for i in ordem]
        total_antes = sum(len(d) for _, d in selecionadas)

        def rodar():
            dados = pt.imagens_para_pdf(
                selecionadas, tamanho_pagina=tamanho, margem_mm=margem,
                recomprimir_jpeg=qualidade,
            )
            return (
                [(pt.nome_seguro(nome_saida or "imagens.pdf"), dados)],
                f"{len(selecionadas)} página(s). "
                + resumo_de_tamanho(total_antes, len(dados)),
            )

        with st.spinner("Montando o PDF..."):
            executar("img2pdf", assinatura, rodar)

    mostrar_resultado("img2pdf", assinatura)


# --------------------------------------------------------------------------


def tela_texto() -> None:
    titulo("📝", "Extrair texto", "Copie o conteúdo escrito do PDF para um arquivo de texto.")

    entrada = receber_pdf("texto")
    if entrada is None:
        return

    intervalo = campo_intervalo("texto", entrada.paginas)
    com_cabecalho = st.checkbox("Marcar o número de cada página no texto", value=True)

    if st.button("Extrair", type="primary", width="stretch"):
        def rodar():
            conteudo, vazias = pt.extrair_texto(
                entrada.dados, intervalo=intervalo,
                com_cabecalho=com_cabecalho, senha=entrada.senha,
            )
            st.session_state["texto_extraido"] = conteudo
            palavras = len(conteudo.split())
            aviso = ""
            if vazias:
                aviso = (
                    f" {vazias} página(s) vieram vazias — provavelmente são "
                    "digitalizações, que guardam só a foto, sem camada de texto."
                )
            return (
                [(pt.sufixar(entrada.nome, "texto", ".txt"), conteudo.encode("utf-8"))],
                f"{palavras} palavra(s) extraída(s)." + aviso,
            )

        with st.spinner("Lendo..."):
            executar("texto", entrada.assinatura, rodar)

    mostrar_resultado("texto", entrada.assinatura, previa=False)

    conteudo = st.session_state.get("texto_extraido")
    if conteudo:
        with st.expander("Ver o texto"):
            st.text_area("Conteúdo", value=conteudo[:20000], height=400,
                         label_visibility="collapsed")
            if len(conteudo) > 20000:
                st.caption("Mostrando os primeiros 20 mil caracteres. O arquivo tem tudo.")
