"""Script auxiliar rodado pelo AppTest (veja tests/interface_test.py).

Troca o `st.file_uploader` por um dublê que devolve arquivos já em memória.
Assim dá para exercitar uma tela inteira - widgets, sessão, botão de download -
sem navegador e sem ninguém clicar em nada.
"""

from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st


class ArquivoFalso:
    """Imita o UploadedFile do Streamlit no que as telas realmente usam."""

    def __init__(self, nome: str, dados: bytes):
        self.name = nome
        self._dados = dados

    def getvalue(self) -> bytes:
        return self._dados

    def read(self) -> bytes:
        return self._dados


# Os arquivos chegam por um pickle em disco: PDFs de teste passam fácil do
# limite de 32 KB de uma variável de ambiente.
_BRUTO = pickle.loads(Path(os.environ["HARNESS_ARQUIVOS"]).read_bytes())
_ORDEM = [
    [ArquivoFalso(nome, dados) for nome, dados in itens]
    for itens in _BRUTO.values()
]
_USADOS = {"n": 0}


def _uploader_falso(rotulo, *args, accept_multiple_files=False, **kwargs):
    """Entrega os arquivos na ordem em que os uploaders aparecem na tela."""
    posicao = _USADOS["n"]
    _USADOS["n"] += 1
    if posicao >= len(_ORDEM):
        return [] if accept_multiple_files else None
    itens = _ORDEM[posicao]
    return itens if accept_multiple_files else (itens[0] if itens else None)


st.file_uploader = _uploader_falso

if os.environ.get("HARNESS_INSTAGRAM"):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import instagram_falso  # noqa: E402

    instagram_falso.instalar()

import interface as ui  # noqa: E402

getattr(ui, os.environ["HARNESS_TELA"])()
