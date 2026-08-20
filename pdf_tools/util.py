"""Utilidades pequenas compartilhadas pelas ferramentas."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Iterable

Arquivo = tuple[str, bytes]  # (nome, conteudo)


def tamanho_legivel(n_bytes: int) -> str:
    """1536 -> '1,5 KB' (com virgula decimal, como se escreve em portugues)."""
    valor = float(n_bytes)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            texto = f"{valor:.0f}" if unidade == "B" else f"{valor:.1f}"
            return f"{texto.replace('.', ',')} {unidade}"
        valor /= 1024
    return f"{valor:.1f} GB"


def variacao_percentual(antes: int, depois: int) -> float:
    """Quanto o arquivo encolheu, em %. Negativo significa que cresceu."""
    if antes <= 0:
        return 0.0
    return (antes - depois) / antes * 100


def nome_base(nome: str) -> str:
    """'relatorio final.pdf' -> 'relatorio final'."""
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", nome or "documento").strip() or "documento"


def nome_seguro(nome: str) -> str:
    """Remove caracteres que quebram download em Windows/macOS."""
    limpo = re.sub(r'[<>:"/\|?*\x00-\x1f]', "-", nome or "").strip(" .")
    return (limpo or "documento")[:120]


def sufixar(nome_original: str, sufixo: str, extensao: str = ".pdf") -> str:
    """'contrato.pdf' + 'assinado' -> 'contrato-assinado.pdf'."""
    return nome_seguro(f"{nome_base(nome_original)}-{sufixo}") + extensao


def zipar(arquivos: Iterable[Arquivo]) -> bytes:
    """Empacota varios resultados em um unico .zip para download."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        usados: set[str] = set()
        for nome, dados in arquivos:
            final = nome_seguro(nome)
            # Nomes repetidos silenciosamente se sobrescrevem dentro do zip.
            if final in usados:
                raiz, _, ext = final.rpartition(".")
                contador = 2
                while final in usados:
                    final = f"{raiz}-{contador}.{ext}" if raiz else f"{final}-{contador}"
                    contador += 1
            usados.add(final)
            zf.writestr(final, dados)
    return buffer.getvalue()


def numerar(indice: int, total: int) -> str:
    """Prefixo zero-padded para nomes de arquivo em lote: 7/120 -> '007'."""
    largura = max(2, len(str(total)))
    return str(indice).zfill(largura)
