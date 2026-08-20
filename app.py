"""Ferramentas de PDF — aplicativo Streamlit.

Rode com:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Ferramentas de PDF",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"about": "Ferramentas de PDF — feito em casa, sem enviar nada para fora."},
)

import interface as ui  # noqa: E402  (precisa vir depois do set_page_config)

ESTILO = """
<style>
  /* Deixa o alvo de upload mais convidativo que o padrão. */
  [data-testid="stFileUploaderDropzone"] { padding: 1.6rem 1rem; }
  /* Botões de girar/remover na grade de páginas ficam compactos. */
  [data-testid="stImage"] img { border-radius: 6px; }
  div.block-container { padding-top: 2.5rem; }
</style>
"""


FERRAMENTAS = [
    ("🔗", "Juntar PDFs", "Vários arquivos em um só, na ordem que você quiser."),
    ("✂️", "Extrair páginas", "Fique só com o trecho que interessa, ou jogue fora o resto."),
    ("🗂️", "Dividir PDF", "Quebra um arquivo grande em vários menores."),
    ("🔄", "Organizar páginas", "Gire as tortas, remova as sobrando, mude a ordem."),
    ("🪶", "Comprimir", "Deixa o arquivo leve o bastante para caber no e-mail."),
    ("🖼️", "PDF para imagens", "Cada página vira um PNG ou JPEG."),
    ("📄", "Imagens para PDF", "Fotos e prints viram um PDF só."),
    ("📝", "Extrair texto", "Copia o conteúdo escrito para um .txt."),
    ("💧", "Marca d'água", "Carimba um texto ou logo nas páginas."),
    ("🔢", "Numerar páginas", "Números no rodapé ou no cabeçalho."),
    ("🔒", "Proteger", "Coloca senha e define o que os outros podem fazer."),
    ("🔓", "Desbloquear", "Tira senha e travas de impressão e cópia."),
    ("ℹ️", "Informações", "Mostra o que tem dentro do arquivo."),
]


def tela_inicio() -> None:
    st.title("📄 Ferramentas de PDF")
    st.markdown(
        "Escolha uma ferramenta no menu à esquerda. "
        "Nenhum arquivo fica guardado: tudo é processado na hora e some quando "
        "você fecha a aba."
    )

    st.divider()
    for faixa in range(0, len(FERRAMENTAS), 3):
        colunas = st.columns(3)
        for coluna, (emoji, nome, descricao) in zip(
            colunas, FERRAMENTAS[faixa : faixa + 3]
        ):
            with coluna.container(border=True):
                st.markdown(f"### {emoji} {nome}")
                st.caption(descricao)

    st.divider()
    with st.expander("Como escrever intervalos de páginas"):
        st.markdown(
            """
            Quase toda ferramenta tem um campo de páginas. Ele entende:

            | O que digitar | O que acontece |
            | --- | --- |
            | *(em branco)* | todas as páginas |
            | `7` | só a página 7 |
            | `1,4,9` | as páginas 1, 4 e 9 |
            | `5-12` | da 5 até a 12 |
            | `10-` | da 10 até o fim |
            | `-4` | do começo até a 4 |
            | `ultima` | a última página |
            | `12-5` | da 12 até a 5, de trás para frente |
            | `1-3, 8, 20-` | pode misturar tudo |
            """
        )

    with st.expander("Qual modo de compressão usar"):
        st.markdown(
            """
            - **Sem perder nada** — o visual fica idêntico. Ganho pequeno, mas
              nunca estraga nada. Comece por aqui se o arquivo for importante.
            - **Recomprimir imagens** — reduz as fotos e mantém o texto
              selecionável. É o melhor custo-benefício na maioria dos casos.
            - **Transformar tudo em imagem** — encolhe muito, mas o texto deixa
              de ser selecionável e a busca para de funcionar. Só para quando
              nada mais resolveu.

            A tela de compressão analisa o arquivo e já sugere o modo provável.
            """
        )


def rodape() -> None:
    with st.sidebar:
        st.divider()
        st.caption(
            "Os arquivos são processados na memória do servidor e não ficam "
            "salvos em lugar nenhum."
        )


st.markdown(ESTILO, unsafe_allow_html=True)

navegacao = st.navigation(
    {
        "Começar": [
            st.Page(tela_inicio, title="Início", icon="🏠", default=True),
        ],
        "Montar e separar": [
            st.Page(ui.tela_juntar, title="Juntar PDFs", icon="🔗"),
            st.Page(ui.tela_extrair, title="Extrair páginas", icon="✂️"),
            st.Page(ui.tela_dividir, title="Dividir PDF", icon="🗂️"),
            st.Page(ui.tela_organizar, title="Organizar páginas", icon="🔄"),
        ],
        "Converter": [
            st.Page(ui.tela_comprimir, title="Comprimir", icon="🪶"),
            st.Page(ui.tela_pdf_para_imagens, title="PDF para imagens", icon="🖼️"),
            st.Page(ui.tela_imagens_para_pdf, title="Imagens para PDF", icon="📄"),
            st.Page(ui.tela_texto, title="Extrair texto", icon="📝"),
        ],
        "Marcar": [
            st.Page(ui.tela_marca_dagua, title="Marca d'água", icon="💧"),
            st.Page(ui.tela_numerar, title="Numerar páginas", icon="🔢"),
        ],
        "Segurança": [
            st.Page(ui.tela_proteger, title="Proteger", icon="🔒"),
            st.Page(ui.tela_desbloquear, title="Desbloquear", icon="🔓"),
            st.Page(ui.tela_informacoes, title="Informações", icon="ℹ️"),
        ],
    }
)

rodape()
navegacao.run()
