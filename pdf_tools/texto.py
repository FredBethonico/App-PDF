"""Extração de texto das páginas."""

from __future__ import annotations

from .imagens import _documento
from .ranges import parse_intervalo


def extrair_texto(
    dados: bytes,
    *,
    intervalo: str = "",
    com_cabecalho: bool = True,
    senha: str = "",
) -> tuple[str, int]:
    """Devolve (texto, número de páginas sem texto).

    Páginas escaneadas voltam vazias: o PDF guarda só a foto, sem camada de
    texto. A contagem devolvida serve para avisar o usuário disso em vez de
    entregar um arquivo em branco sem explicação.
    """
    doc = _documento(dados, senha)
    try:
        indices = parse_intervalo(intervalo, len(doc))
        partes: list[str] = []
        vazias = 0
        for indice in indices:
            pagina = doc[indice]
            camada = pagina.get_textpage()
            try:
                conteudo = camada.get_text_range().strip()
            finally:
                camada.close()
            if not conteudo:
                vazias += 1
            if com_cabecalho:
                partes.append(f"--- Página {indice + 1} ---\n{conteudo}")
            elif conteudo:
                partes.append(conteudo)
        return "\n\n".join(partes), vazias
    finally:
        doc.close()
