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

  /* Cartões da tela inicial: links com cara (e comportamento) de botão. */
  .st-key-cartoes a[data-testid="stPageLink-NavLink"] {
    padding: 1rem 1.1rem;
    border: 1px solid rgba(128, 128, 128, 0.3);
    border-radius: 0.6rem;
    align-items: flex-start;
    transition: border-color .15s, box-shadow .15s, transform .15s;
  }
  .st-key-cartoes a[data-testid="stPageLink-NavLink"]:hover {
    border-color: var(--primary-color, #ff4b4b);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
    transform: translateY(-1px);
  }
  .st-key-cartoes a[data-testid="stPageLink-NavLink"]:active { transform: none; }
  /* Na grade de 3 colunas, cartões da mesma linha ficam com altura parecida. */
  @media (min-width: 640px) {
    .st-key-cartoes a[data-testid="stPageLink-NavLink"] { min-height: 6.5rem; }
  }
  /* Por padrão o Streamlit corta o rótulo em uma linha só; aqui ele quebra. */
  .st-key-cartoes a[data-testid="stPageLink-NavLink"] span,
  .st-key-cartoes a[data-testid="stPageLink-NavLink"] div,
  .st-key-cartoes a[data-testid="stPageLink-NavLink"] p {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
  }
  .st-key-cartoes a[data-testid="stPageLink-NavLink"] p {
    line-height: 1.5;
  }
  .st-key-cartoes a[data-testid="stPageLink-NavLink"] strong { font-size: 1.15rem; }
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
    ("📚", "EPUB para PDF", "Livros digitais viram PDF, com sumário e links clicáveis."),
    ("📐", "Redimensionar imagens", "Várias imagens de uma vez, no tamanho em pixels que você digitar."),
    ("🪄", "Remover fundo", "Fundo transparente ou em cor sólida, com retoque a pincel."),
    ("📸", "Baixar do Instagram", "Fotos, vídeos e carrosséis de posts públicos, pelo link."),
    ("🎵", "MP4 para MP3", "Tira o som de vídeos e salva como MP3, inteiro ou só um trecho."),
    ("💧", "Marca d'água", "Carimba um texto ou logo nas páginas."),
    ("🔢", "Numerar páginas", "Números no rodapé ou no cabeçalho."),
    ("🔒", "Proteger", "Coloca senha e define o que os outros podem fazer."),
    ("🔓", "Desbloquear", "Tira senha e travas de impressão e cópia."),
    ("ℹ️", "Informações", "Mostra o que tem dentro do arquivo."),
]


def tela_inicio() -> None:
    st.title("📄 Ferramentas de PDF")
    st.markdown(
        "Escolha uma ferramenta abaixo ou no menu à esquerda. "
        "Nenhum arquivo fica guardado: tudo é processado na hora e some quando "
        "você fecha a aba."
    )

    st.divider()
    # Cada cartão é um link de verdade para a ferramenta (o CSS em ESTILO dá
    # a cara de botão). Usa as mesmas páginas do menu lateral.
    with st.container(key="cartoes"):
        for faixa in range(0, len(FERRAMENTAS), 3):
            colunas = st.columns(3)
            for coluna, (emoji, nome, descricao) in zip(
                colunas, FERRAMENTAS[faixa : faixa + 3]
            ):
                with coluna:
                    st.page_link(
                        PAGINAS[nome],
                        label=f"**{nome}**  \n{descricao}",
                        icon=emoji,
                        width="stretch",
                    )

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

SECOES = {
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
        st.Page(ui.tela_epub_para_pdf, title="EPUB para PDF", icon="📚"),
    ],
    "Imagens": [
        st.Page(ui.tela_redimensionar, title="Redimensionar imagens", icon="📐"),
        st.Page(ui.tela_remover_fundo, title="Remover fundo", icon="🪄"),
    ],
    "Internet": [
        st.Page(ui.tela_instagram, title="Baixar do Instagram", icon="📸"),
    ],
    "Áudio e vídeo": [
        st.Page(ui.tela_mp4_para_mp3, title="MP4 para MP3", icon="🎵"),
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
PAGINAS = {p.title: p for paginas in SECOES.values() for p in paginas}
navegacao = st.navigation(SECOES)

rodape()
navegacao.run()
