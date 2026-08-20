"""Ferramentas de edição de PDF.

Tudo aqui é função pura sobre `bytes`: recebe o conteúdo de um arquivo e
devolve o conteúdo do resultado. Nada toca no disco e nada importa Streamlit,
então dá para usar em script, notebook ou testes do mesmo jeito.
"""

from .comprimir import (
    NIVEIS,
    comprimir_estrutura,
    comprimir_imagens,
    diagnostico,
    rasterizar,
)
from .documento import (
    Info,
    PdfInvalido,
    PdfProtegido,
    desbloquear,
    inspecionar,
    precisa_de_senha,
    proteger,
)
from .imagens import (
    FORMATOS_ENTRADA,
    TAMANHOS_PAGINA,
    contar_paginas,
    imagens_para_pdf,
    miniaturas,
    pdf_para_imagens,
    renderizar_pagina,
)
from .marcas import (
    FONTES,
    POSICOES,
    marca_dagua_imagem,
    marca_dagua_texto,
    numerar_paginas,
)
from .paginas import (
    dividir_em_blocos,
    dividir_em_partes,
    dividir_por_intervalos,
    extrair,
    girar_tudo,
    juntar,
    organizar,
    remover,
)
from .ranges import ErroDeIntervalo, formatar_intervalo, parse_intervalo
from .texto import extrair_texto
from .util import (
    nome_base,
    nome_seguro,
    sufixar,
    tamanho_legivel,
    variacao_percentual,
    zipar,
)

__all__ = [
    "ErroDeIntervalo",
    "FONTES",
    "FORMATOS_ENTRADA",
    "Info",
    "NIVEIS",
    "POSICOES",
    "PdfInvalido",
    "PdfProtegido",
    "TAMANHOS_PAGINA",
    "comprimir_estrutura",
    "comprimir_imagens",
    "contar_paginas",
    "desbloquear",
    "diagnostico",
    "dividir_em_blocos",
    "dividir_em_partes",
    "dividir_por_intervalos",
    "extrair",
    "extrair_texto",
    "formatar_intervalo",
    "girar_tudo",
    "imagens_para_pdf",
    "inspecionar",
    "juntar",
    "marca_dagua_imagem",
    "marca_dagua_texto",
    "miniaturas",
    "nome_base",
    "nome_seguro",
    "numerar_paginas",
    "organizar",
    "parse_intervalo",
    "pdf_para_imagens",
    "precisa_de_senha",
    "proteger",
    "rasterizar",
    "remover",
    "renderizar_pagina",
    "sufixar",
    "tamanho_legivel",
    "variacao_percentual",
    "zipar",
]
