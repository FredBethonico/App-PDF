"""Camada de interface Streamlit.

Cada tela é uma função sem argumentos que desenha uma ferramenta inteira.
Toda a lógica de PDF vive em `pdf_tools`; aqui só tem widget e mensagem.
"""

from .telas_audio import tela_mp4_para_mp3
from .telas_imagens import tela_redimensionar
from .telas_instagram import tela_instagram
from .telas_converter import (
    tela_comprimir,
    tela_imagens_para_pdf,
    tela_pdf_para_imagens,
    tela_texto,
)
from .telas_marcas import tela_marca_dagua, tela_numerar
from .telas_paginas import tela_dividir, tela_extrair, tela_juntar, tela_organizar
from .telas_seguranca import tela_desbloquear, tela_informacoes, tela_proteger

__all__ = [
    "tela_comprimir",
    "tela_desbloquear",
    "tela_dividir",
    "tela_extrair",
    "tela_imagens_para_pdf",
    "tela_informacoes",
    "tela_instagram",
    "tela_juntar",
    "tela_marca_dagua",
    "tela_mp4_para_mp3",
    "tela_numerar",
    "tela_organizar",
    "tela_pdf_para_imagens",
    "tela_proteger",
    "tela_redimensionar",
    "tela_texto",
]
