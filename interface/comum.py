"""Peças de interface reaproveitadas por todas as telas."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import streamlit as st

import pdf_tools as pt
from pdf_tools.util import Arquivo

LIMITE_PREVIA_MB = 60  # acima disso a prévia sai cara e a tela trava


@dataclass
class Entrada:
    """Um PDF já validado e pronto para ser processado."""

    nome: str
    dados: bytes
    senha: str
    info: pt.Info

    @property
    def assinatura(self) -> str:
        """Identidade do arquivo, para invalidar resultados antigos na tela."""
        return hashlib.md5(self.dados[:200_000] + str(len(self.dados)).encode()).hexdigest()

    @property
    def paginas(self) -> int:
        return self.info.paginas


# --------------------------------------------------------------------------
# Cache: as funções pesadas recebem bytes, que o Streamlit sabe versionar.
# --------------------------------------------------------------------------


@st.cache_data(show_spinner=False, max_entries=8)
def _inspecionar(dados: bytes, senha: str) -> pt.Info:
    return pt.inspecionar(dados, senha)


@st.cache_data(show_spinner=False, max_entries=4)
def _precisa_de_senha(dados: bytes) -> bool:
    return pt.precisa_de_senha(dados)


@st.cache_data(show_spinner="Gerando prévia...", max_entries=4)
def miniaturas_png(
    dados: bytes, indices: tuple[int, ...], largura: int, senha: str
) -> list[bytes]:
    """Miniaturas em PNG (bytes viajam melhor pelo cache que objetos PIL)."""
    saida = []
    for imagem in pt.miniaturas(dados, list(indices), largura=largura, senha=senha):
        buffer = io.BytesIO()
        imagem.save(buffer, "PNG")
        saida.append(buffer.getvalue())
    return saida


@st.cache_data(show_spinner=False, max_entries=4)
def _diagnostico(dados: bytes, senha: str) -> dict:
    return pt.diagnostico(dados, senha)


@st.cache_data(show_spinner=False, max_entries=4)
def _camada_de_texto(dados: bytes, senha: str) -> tuple[int, int]:
    """(palavras, páginas com texto) — quanto se perde ao rasterizar."""
    try:
        # Sem cabeçalho: senão os "--- Página N ---" entram na contagem.
        texto, vazias = pt.extrair_texto(dados, senha=senha, com_cabecalho=False)
    except Exception:
        return 0, 0
    return len(texto.split()), vazias


# --------------------------------------------------------------------------
# Entrada de arquivos
# --------------------------------------------------------------------------


def receber_pdf(
    chave: str, rotulo: str = "Arraste o PDF aqui ou clique para escolher"
) -> Entrada | None:
    """Uploader + senha + cartão de informações. None enquanto não estiver pronto."""
    enviado = st.file_uploader(rotulo, type="pdf", key=f"upload_{chave}")
    if enviado is None:
        return None

    dados = enviado.getvalue()
    if not dados:
        st.error("O arquivo chegou vazio. Tente enviar de novo.")
        return None

    senha = ""
    if _precisa_de_senha(dados):
        st.warning("Este PDF pede senha para abrir.")
        senha = st.text_input(
            "Senha de abertura", type="password", key=f"senha_{chave}"
        )
        if not senha:
            return None

    try:
        info = _inspecionar(dados, senha)
    except pt.PdfProtegido as erro:
        st.error(str(erro))
        return None
    except pt.PdfInvalido as erro:
        st.error(str(erro))
        return None

    entrada = Entrada(enviado.name, dados, senha, info)
    cartao_do_arquivo(entrada)
    return entrada


def receber_varios_pdfs(chave: str, rotulo: str = "Escolha os PDFs") -> list[Arquivo]:
    enviados = st.file_uploader(
        rotulo, type="pdf", accept_multiple_files=True, key=f"upload_{chave}"
    )
    return [(arquivo.name, arquivo.getvalue()) for arquivo in enviados or []]


def receber_imagens(chave: str, rotulo: str = "Escolha as imagens") -> list[Arquivo]:
    enviados = st.file_uploader(
        rotulo,
        type=pt.FORMATOS_ENTRADA,
        accept_multiple_files=True,
        key=f"upload_{chave}",
    )
    return [(arquivo.name, arquivo.getvalue()) for arquivo in enviados or []]


def cartao_do_arquivo(entrada: Entrada) -> None:
    """Faixa com os números do arquivo, igual em todas as telas."""
    colunas = st.columns([3, 1, 1, 1])
    colunas[0].markdown(f"**{entrada.nome}**")
    colunas[1].metric("Páginas", entrada.paginas)
    colunas[2].metric("Tamanho", pt.tamanho_legivel(entrada.info.tamanho))
    formato = entrada.info.descricao_pagina(0) if entrada.info.tamanhos_pagina else "-"
    colunas[3].metric("Formato", formato.split(" (")[-1].rstrip(")").title())

    detalhes = []
    if not entrada.info.paginas_iguais:
        detalhes.append("as páginas têm tamanhos diferentes")
    if entrada.info.criptografado:
        bloqueado = [n for n, v in entrada.info.permissoes.items() if not v]
        if bloqueado:
            detalhes.append("restrições ativas: " + ", ".join(bloqueado).lower())
    if detalhes:
        st.caption("Atenção: " + "; ".join(detalhes) + ".")


# --------------------------------------------------------------------------
# Saída de arquivos
# --------------------------------------------------------------------------


def _chave_resultado(chave: str) -> str:
    return f"resultado_{chave}"


def guardar_resultado(
    chave: str, entrada_assinatura: str, arquivos: list[Arquivo], resumo: str = ""
) -> None:
    """Guarda o resultado na sessão.

    Sem isso, o clique no botão de download provoca um rerun, o resultado
    se perde e o download vem vazio.
    """
    st.session_state[_chave_resultado(chave)] = {
        "assinatura": entrada_assinatura,
        "arquivos": arquivos,
        "resumo": resumo,
    }


def limpar_resultado(chave: str) -> None:
    st.session_state.pop(_chave_resultado(chave), None)


def mostrar_resultado(
    chave: str,
    entrada_assinatura: str,
    *,
    nome_do_zip: str = "resultado.zip",
    previa: bool = True,
) -> None:
    """Botões de download do último resultado, se ainda for do arquivo atual."""
    guardado = st.session_state.get(_chave_resultado(chave))
    if not guardado or guardado["assinatura"] != entrada_assinatura:
        return

    arquivos: list[Arquivo] = guardado["arquivos"]
    if not arquivos:
        return

    st.divider()
    st.subheader("Pronto")
    if guardado["resumo"]:
        st.success(guardado["resumo"])

    if len(arquivos) == 1:
        nome, dados = arquivos[0]
        st.download_button(
            f"Baixar {nome}",
            data=dados,
            file_name=nome,
            mime=_tipo(nome),
            type="primary",
            width="stretch",
            key=f"baixar_{chave}",
        )
        if previa and nome.lower().endswith(".pdf"):
            previa_pdf(dados)
    else:
        st.download_button(
            f"Baixar tudo em .zip ({len(arquivos)} arquivos)",
            data=pt.zipar(arquivos),
            file_name=pt.nome_seguro(nome_do_zip),
            mime="application/zip",
            type="primary",
            width="stretch",
            key=f"baixar_zip_{chave}",
        )
        with st.expander(f"Baixar um a um ({len(arquivos)})"):
            for posicao, (nome, dados) in enumerate(arquivos):
                colunas = st.columns([4, 2, 2])
                colunas[0].write(nome)
                colunas[1].caption(pt.tamanho_legivel(len(dados)))
                colunas[2].download_button(
                    "Baixar",
                    data=dados,
                    file_name=nome,
                    mime=_tipo(nome),
                    key=f"baixar_{chave}_{posicao}",
                    width="stretch",
                )


def _tipo(nome: str) -> str:
    fim = nome.lower().rsplit(".", 1)[-1]
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "txt": "text/plain",
        "mp4": "video/mp4",
        "zip": "application/zip",
    }.get(fim, "application/octet-stream")


def previa_pdf(dados: bytes, paginas: int = 3, largura: int = 260) -> None:
    """Mostra as primeiras páginas do resultado, para conferir antes de baixar."""
    if len(dados) > LIMITE_PREVIA_MB * 1024 * 1024:
        st.caption("Arquivo grande demais para a prévia — baixe para conferir.")
        return
    try:
        total = pt.contar_paginas(dados)
        indices = tuple(range(min(paginas, total)))
        imagens = miniaturas_png(dados, indices, largura, "")
    except Exception:
        return  # a prévia é um extra: se falhar, o download continua valendo

    with st.expander(f"Ver prévia ({len(indices)} de {total} páginas)", expanded=True):
        for coluna, (indice, imagem) in zip(st.columns(len(imagens)), enumerate(imagens)):
            coluna.image(imagem, caption=f"Página {indice + 1}", width="stretch")


# --------------------------------------------------------------------------
# Diversos
# --------------------------------------------------------------------------


def executar(chave: str, entrada_assinatura: str, funcao, *, resumo_fn=None) -> None:
    """Roda a operação tratando erros com mensagem legível em vez de traceback."""
    try:
        arquivos = funcao()
    except pt.ErroDeIntervalo as erro:
        st.error(f"Intervalo de páginas: {erro}")
        return
    except (pt.PdfProtegido, pt.PdfInvalido) as erro:
        st.error(str(erro))
        return
    except ValueError as erro:
        st.error(str(erro))
        return
    except Exception as erro:  # rede de segurança: o app não pode quebrar na cara
        st.error(f"Não consegui concluir: {erro}")
        st.caption("Se o arquivo for incomum, tente antes a ferramenta Desbloquear.")
        return

    if isinstance(arquivos, tuple):
        arquivos, resumo = arquivos
    else:
        resumo = resumo_fn() if resumo_fn else ""
    guardar_resultado(chave, entrada_assinatura, arquivos, resumo)


def resumo_de_tamanho(antes: int, depois: int) -> str:
    variacao = pt.variacao_percentual(antes, depois)
    de_para = f"{pt.tamanho_legivel(antes)} → {pt.tamanho_legivel(depois)}"
    if variacao > 0.5:
        return f"{de_para} — {variacao:.0f}% menor."
    if variacao < -0.5:
        return f"{de_para} — o arquivo cresceu {abs(variacao):.0f}%. Tente outro modo."
    return f"{de_para} — praticamente o mesmo tamanho."


def campo_intervalo(
    chave: str, total: int, rotulo: str = "Páginas", padrao: str = ""
) -> str:
    """Campo de intervalo com a ajuda de sintaxe sempre à mão."""
    return st.text_input(
        rotulo,
        value=padrao,
        key=f"intervalo_{chave}",
        placeholder=f"em branco = todas (1 a {total})",
        help=(
            "Exemplos: **3** (só a 3), **1,4,9** (soltas), **5-12** (intervalo), "
            "**10-** (da 10 até o fim), **ultima**. "
            "Invertido também vale: **12-5** entrega as páginas de trás para frente."
        ),
    )


def titulo(emoji: str, texto: str, explicacao: str) -> None:
    st.title(f"{emoji} {texto}")
    st.caption(explicacao)
