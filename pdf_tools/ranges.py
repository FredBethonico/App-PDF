"""Interpretacao de intervalos de paginas digitados pelo usuario."""

from __future__ import annotations

import re

_SEPARADORES = re.compile(r"[;,\n]+")
# O "a"/"ate" so conta como separador cercado de espacos, senao palavras
# como "ultima" seriam quebradas no meio.
_TRACOS = re.compile(r"\s*(?:-{1,2}|–|—|:)\s*|\s+at?[eé]?\s+", re.IGNORECASE)


class ErroDeIntervalo(ValueError):
    """Digitacao de intervalo invalida."""


def parse_intervalo(spec: str, total: int) -> list[int]:
    """Converte '1,3,5-7' em indices 0-based [0, 2, 4, 5, 6].

    Aceita:
      - paginas soltas:      "1, 4, 9"
      - intervalos:          "5-7", "5 a 7", "5:7", "5--7"
      - aberto no fim:       "10-"   (da 10 ate a ultima)
      - aberto no inicio:    "-5"    (da 1 ate a 5)
      - tudo:                "" ou "todas" ou "*"
      - contagem pelo fim:   "-1" nao e suportado (conflita com "ate 1");
                             use "ultima" ou "final" para a ultima pagina.

    Intervalos invertidos ("7-5") sao lidos na ordem inversa, o que permite
    usar a mesma sintaxe para reordenar paginas. Duplicatas sao preservadas
    (extrair "1,1,1" gera tres copias da pagina 1) porque isso e util em
    montagem de material impresso.
    """
    if total <= 0:
        raise ErroDeIntervalo("O PDF não tem páginas.")

    spec = (spec or "").strip()
    if not spec or spec.lower() in {"*", "todas", "todos", "all", "tudo"}:
        return list(range(total))

    indices: list[int] = []
    for bruto in _SEPARADORES.split(spec):
        parte = bruto.strip()
        if not parte:
            continue
        indices.extend(_parse_parte(parte, total))

    if not indices:
        raise ErroDeIntervalo(f"Não consegui entender {spec!r}.")
    return indices


def _palavra_para_pagina(token: str, total: int) -> int | None:
    t = token.strip().lower()
    if t in {"ultima", "ultimo", "final", "fim", "last", "end"}:
        return total
    if t in {"primeira", "primeiro", "inicio", "first"}:
        return 1
    return None


def _numero(token: str, total: int, campo: str) -> int:
    palavra = _palavra_para_pagina(token, total)
    if palavra is not None:
        return palavra
    try:
        return int(token)
    except ValueError:
        raise ErroDeIntervalo(
            f"{campo} inválido: {token!r}. Use números, como 3 ou 5-9."
        ) from None


def _parse_parte(parte: str, total: int) -> list[int]:
    pedacos = _TRACOS.split(parte)
    # "5-7" -> ["5", "7"]; "10-" -> ["10", ""]; "-5" -> ["", "5"]
    if len(pedacos) == 1:
        pagina = _numero(pedacos[0], total, "Página")
        _conferir(pagina, total)
        return [pagina - 1]

    if len(pedacos) != 2:
        raise ErroDeIntervalo(
            f"Intervalo inválido: {parte!r}. Use o formato 5-9."
        )

    ini_txt, fim_txt = pedacos
    inicio = _numero(ini_txt, total, "Início do intervalo") if ini_txt.strip() else 1
    fim = _numero(fim_txt, total, "Fim do intervalo") if fim_txt.strip() else total

    _conferir(inicio, total)
    _conferir(fim, total)

    if inicio <= fim:
        return list(range(inicio - 1, fim))
    return list(range(inicio - 1, fim - 2, -1))


def _conferir(pagina: int, total: int) -> None:
    if pagina < 1 or pagina > total:
        raise ErroDeIntervalo(
            f"A página {pagina} não existe: o arquivo tem {total} página(s)."
        )


def formatar_intervalo(indices: list[int]) -> str:
    """Inverso amigavel de parse_intervalo: [0,1,2,5] -> '1-3, 6'."""
    if not indices:
        return ""
    paginas = [i + 1 for i in indices]
    blocos: list[str] = []
    inicio = anterior = paginas[0]
    for pagina in paginas[1:]:
        if pagina == anterior + 1:
            anterior = pagina
            continue
        blocos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        inicio = anterior = pagina
    blocos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
    return ", ".join(blocos)
