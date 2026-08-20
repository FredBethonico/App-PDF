"""Abertura, diagnostico, protecao e desbloqueio de PDFs."""

from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import dataclass, field

import pikepdf


class PdfProtegido(Exception):
    """O arquivo precisa de senha (ou a senha informada esta errada)."""


class PdfInvalido(Exception):
    """O arquivo nao e um PDF legivel."""


@contextmanager
def abrir(dados: bytes, senha: str = ""):
    """Abre bytes como PDF, traduzindo os erros do qpdf para mensagens uteis.

    Sempre use como context manager: o pikepdf mantem o buffer aberto e
    fechar cedo demais invalida objetos ainda em uso na hora de salvar.
    """
    try:
        pdf = pikepdf.open(io.BytesIO(dados), password=senha or "")
    except pikepdf.PasswordError:
        raise PdfProtegido(
            "Este PDF está protegido por senha. Informe a senha de abertura."
            if not senha
            else "Senha incorreta para este PDF."
        ) from None
    except pikepdf.PdfError as erro:
        raise PdfInvalido(
            f"Não consegui ler este arquivo como PDF ({erro})."
        ) from None
    try:
        yield pdf
    finally:
        pdf.close()


def salvar(pdf: pikepdf.Pdf, **kwargs) -> bytes:
    """Serializa um Pdf aberto para bytes."""
    buffer = io.BytesIO()
    pdf.save(buffer, **kwargs)
    return buffer.getvalue()


@dataclass
class Info:
    paginas: int
    tamanho: int
    criptografado: bool
    versao: str
    titulo: str = ""
    autor: str = ""
    criador: str = ""
    produtor: str = ""
    tamanhos_pagina: list[tuple[float, float]] = field(default_factory=list)
    permissoes: dict[str, bool] = field(default_factory=dict)

    @property
    def paginas_iguais(self) -> bool:
        return len(set(self.tamanhos_pagina)) <= 1

    def descricao_pagina(self, indice: int = 0) -> str:
        """'21,0 x 29,7 cm (A4 retrato)'."""
        if not self.tamanhos_pagina:
            return "-"
        largura_pt, altura_pt = self.tamanhos_pagina[indice]
        largura_cm, altura_cm = largura_pt / 72 * 2.54, altura_pt / 72 * 2.54
        nome = _nome_do_formato(largura_cm, altura_cm)
        orientacao = "paisagem" if largura_pt > altura_pt else "retrato"
        rotulo = f"{largura_cm:.1f} x {altura_cm:.1f} cm".replace(".", ",")
        return f"{rotulo} ({nome} {orientacao})" if nome else f"{rotulo} ({orientacao})"


_FORMATOS_CM = {
    "A3": (29.7, 42.0),
    "A4": (21.0, 29.7),
    "A5": (14.8, 21.0),
    "Carta": (21.6, 27.9),
    "Oficio": (21.6, 35.6),
}


def _nome_do_formato(largura_cm: float, altura_cm: float, tolerancia: float = 0.4) -> str:
    menor, maior = sorted((largura_cm, altura_cm))
    for nome, (fmt_menor, fmt_maior) in _FORMATOS_CM.items():
        if abs(menor - fmt_menor) < tolerancia and abs(maior - fmt_maior) < tolerancia:
            return nome
    return ""


def _texto(valor) -> str:
    if valor is None:
        return ""
    try:
        return str(valor).strip()
    except Exception:
        return ""


def inspecionar(dados: bytes, senha: str = "") -> Info:
    """Le metadados sem alterar nada. Usado no cabecalho de toda ferramenta."""
    with abrir(dados, senha) as pdf:
        docinfo = pdf.docinfo if pdf.trailer.get("/Info") is not None else {}
        tamanhos: list[tuple[float, float]] = []
        for pagina in pdf.pages:
            caixa = pikepdf.Rectangle(pagina.mediabox)
            largura, altura = caixa.width, caixa.height
            # /Rotate 90 ou 270 troca o que o leitor mostra na tela.
            if int(pagina.obj.get("/Rotate", 0)) % 180 == 90:
                largura, altura = altura, largura
            tamanhos.append((round(largura, 1), round(altura, 1)))

        permissoes = {}
        if pdf.is_encrypted:
            p = pdf.allow
            permissoes = {
                "Imprimir": bool(p.print_lowres or p.print_highres),
                "Copiar texto": bool(p.extract),
                "Editar": bool(p.modify_other),
                "Preencher formularios": bool(p.modify_form),
                "Comentar": bool(p.modify_annotation),
            }

        return Info(
            paginas=len(pdf.pages),
            tamanho=len(dados),
            criptografado=pdf.is_encrypted,
            versao=pdf.pdf_version,
            titulo=_texto(docinfo.get("/Title")),
            autor=_texto(docinfo.get("/Author")),
            criador=_texto(docinfo.get("/Creator")),
            produtor=_texto(docinfo.get("/Producer")),
            tamanhos_pagina=tamanhos,
            permissoes=permissoes,
        )


def precisa_de_senha(dados: bytes) -> bool:
    """True quando nem a leitura e possivel sem senha de usuario."""
    try:
        with abrir(dados):
            return False
    except PdfProtegido:
        return True
    except PdfInvalido:
        return False


def desbloquear(dados: bytes, senha: str = "") -> bytes:
    """Remove criptografia e restricoes, gerando um PDF livre.

    Funciona em dois casos:
      - PDF com senha de dono (abre normal, mas bloqueia imprimir/copiar):
        nao precisa informar senha nenhuma;
      - PDF com senha de usuario: e preciso informar a senha de abertura.
    """
    with abrir(dados, senha) as pdf:
        # save() sem encryption= grava o documento sem nenhuma protecao.
        return salvar(pdf, compress_streams=True)


def proteger(
    dados: bytes,
    senha_abertura: str = "",
    senha_dono: str = "",
    *,
    permitir_impressao: bool = True,
    permitir_copia: bool = True,
    permitir_edicao: bool = False,
    permitir_anotacoes: bool = True,
    senha_atual: str = "",
) -> bytes:
    """Aplica senha e restricoes com AES-256 (R=6)."""
    if not senha_abertura and not senha_dono:
        raise ValueError(
            "Informe pelo menos uma senha: a de abertura (para ler) "
            "ou a de dono (para liberar a edição)."
        )

    permissoes = pikepdf.Permissions(
        accessibility=True,
        extract=permitir_copia,
        modify_annotation=permitir_anotacoes,
        modify_assembly=permitir_edicao,
        modify_form=permitir_anotacoes,
        modify_other=permitir_edicao,
        print_lowres=permitir_impressao,
        print_highres=permitir_impressao,
    )
    # Sem senha de dono explicita, o PDF ficaria destravavel por qualquer um;
    # reaproveitar a de abertura mantem as restricoes de pe.
    dono = senha_dono or senha_abertura
    with abrir(dados, senha_atual) as pdf:
        return salvar(
            pdf,
            encryption=pikepdf.Encryption(
                owner=dono, user=senha_abertura, R=6, allow=permissoes
            ),
        )
