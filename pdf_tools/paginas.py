"""Operacoes sobre paginas: extrair, dividir, juntar e organizar."""

from __future__ import annotations

import math
from contextlib import ExitStack

import pikepdf

from .documento import abrir, salvar
from .ranges import parse_intervalo
from .util import Arquivo, nome_base, nome_seguro, numerar

# Reduz o tamanho de qualquer recorte: sem isso o qpdf carrega junto fontes e
# imagens do documento inteiro, mesmo extraindo uma unica pagina.
_LIMPEZA = dict(compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)


def _montar(origem: pikepdf.Pdf, indices: list[int]) -> bytes:
    destino = pikepdf.Pdf.new()
    for i in indices:
        destino.pages.append(origem.pages[i])
    destino.remove_unreferenced_resources()
    return salvar(destino, **_LIMPEZA)


def extrair(dados: bytes, intervalo: str, senha: str = "") -> bytes:
    """Gera um PDF novo so com as paginas pedidas, na ordem pedida."""
    with abrir(dados, senha) as pdf:
        indices = parse_intervalo(intervalo, len(pdf.pages))
        return _montar(pdf, indices)


def remover(dados: bytes, intervalo: str, senha: str = "") -> bytes:
    """O inverso de extrair: descarta as paginas indicadas."""
    with abrir(dados, senha) as pdf:
        total = len(pdf.pages)
        descartar = set(parse_intervalo(intervalo, total))
        restantes = [i for i in range(total) if i not in descartar]
        if not restantes:
            raise ValueError("Isso removeria todas as páginas do documento.")
        return _montar(pdf, restantes)


def dividir_em_blocos(
    dados: bytes, paginas_por_arquivo: int, nome: str = "documento", senha: str = ""
) -> list[Arquivo]:
    """Fatia o PDF a cada N paginas."""
    if paginas_por_arquivo < 1:
        raise ValueError("Cada arquivo precisa ter pelo menos 1 página.")
    with abrir(dados, senha) as pdf:
        total = len(pdf.pages)
        blocos = [
            list(range(inicio, min(inicio + paginas_por_arquivo, total)))
            for inicio in range(0, total, paginas_por_arquivo)
        ]
        return _exportar_blocos(pdf, blocos, nome)


def dividir_em_partes(
    dados: bytes, quantidade: int, nome: str = "documento", senha: str = ""
) -> list[Arquivo]:
    """Divide em N arquivos do tamanho mais parecido possivel."""
    if quantidade < 1:
        raise ValueError("Informe pelo menos 1 parte.")
    with abrir(dados, senha) as pdf:
        total = len(pdf.pages)
        if quantidade > total:
            raise ValueError(
                f"Não dá para dividir {total} página(s) em {quantidade} partes."
            )
        # Distribui o resto entre os primeiros arquivos: 6 paginas em 4 partes
        # vira 2+2+1+1, e nao 2+2+2 (que perderia uma parte inteira).
        por_parte, resto = divmod(total, quantidade)
        blocos = []
        inicio = 0
        for posicao in range(quantidade):
            fim = inicio + por_parte + (1 if posicao < resto else 0)
            blocos.append(list(range(inicio, fim)))
            inicio = fim
        return _exportar_blocos(pdf, blocos, nome)


def dividir_por_intervalos(
    dados: bytes, intervalos: list[str], nome: str = "documento", senha: str = ""
) -> list[Arquivo]:
    """Um arquivo de saida para cada intervalo digitado."""
    intervalos = [i.strip() for i in intervalos if i and i.strip()]
    if not intervalos:
        raise ValueError("Digite pelo menos um intervalo, por exemplo 1-10.")
    with abrir(dados, senha) as pdf:
        total = len(pdf.pages)
        blocos = [parse_intervalo(intervalo, total) for intervalo in intervalos]
        return _exportar_blocos(pdf, blocos, nome)


def _exportar_blocos(
    pdf: pikepdf.Pdf, blocos: list[list[int]], nome: str
) -> list[Arquivo]:
    base = nome_base(nome)
    total = len(blocos)
    saida: list[Arquivo] = []
    for posicao, indices in enumerate(blocos, start=1):
        if not indices:
            continue
        primeira, ultima = indices[0] + 1, indices[-1] + 1
        faixa = f"p{primeira}" if primeira == ultima else f"p{primeira}-{ultima}"
        rotulo = f"{base}-{numerar(posicao, total)}-{faixa}.pdf"
        saida.append((nome_seguro(rotulo), _montar(pdf, indices)))
    return saida


def juntar(arquivos: list[Arquivo], *, com_indice: bool = True) -> bytes:
    """Concatena varios PDFs, opcionalmente criando marcadores por arquivo.

    O qpdf le os streams das origens preguicosamente, entao todos os PDFs de
    entrada precisam continuar abertos ate o save final - dai a ExitStack.
    """
    if len(arquivos) < 2:
        raise ValueError("Selecione pelo menos dois PDFs para juntar.")

    destino = pikepdf.Pdf.new()
    marcadores: list[tuple[str, int]] = []
    with ExitStack() as pilha:
        for nome, dados in arquivos:
            origem = pilha.enter_context(abrir(dados))
            marcadores.append((nome_base(nome), len(destino.pages)))
            destino.pages.extend(origem.pages)

        if com_indice:
            with destino.open_outline() as sumario:
                for titulo, primeira_pagina in marcadores:
                    sumario.root.append(pikepdf.OutlineItem(titulo, primeira_pagina))

        destino.remove_unreferenced_resources()
        return salvar(destino, **_LIMPEZA)


def organizar(
    dados: bytes,
    ordem: list[int],
    rotacoes: dict[int, int] | None = None,
    senha: str = "",
) -> bytes:
    """Reordena/remove paginas e aplica giros.

    ordem: indices 0-based do documento original, na sequencia desejada.
    rotacoes: {indice_original: graus} com graus em 0/90/180/270, relativos
              a rotacao que a pagina ja tinha.
    """
    rotacoes = rotacoes or {}
    if not ordem:
        raise ValueError("Nenhuma página sobrou: mantenha ao menos uma.")

    with abrir(dados, senha) as pdf:
        total = len(pdf.pages)
        fora = [i + 1 for i in ordem if not 0 <= i < total]
        if fora:
            raise ValueError(f"Páginas inexistentes: {fora}.")

        destino = pikepdf.Pdf.new()
        for indice in ordem:
            destino.pages.append(pdf.pages[indice])
            giro = rotacoes.get(indice, 0) % 360
            if giro:
                pikepdf.Page(destino.pages[-1]).rotate(giro, relative=True)
        destino.remove_unreferenced_resources()
        return salvar(destino, **_LIMPEZA)


def girar_tudo(dados: bytes, graus: int, intervalo: str = "", senha: str = "") -> bytes:
    """Atalho para girar todas (ou algumas) paginas de uma vez."""
    with abrir(dados, senha) as pdf:
        total = len(pdf.pages)
        alvos = parse_intervalo(intervalo, total)
        destino = pikepdf.Pdf.new()
        destino.pages.extend(pdf.pages)
        for indice in set(alvos):
            pikepdf.Page(destino.pages[indice]).rotate(graus % 360, relative=True)
        destino.remove_unreferenced_resources()
        return salvar(destino, **_LIMPEZA)
