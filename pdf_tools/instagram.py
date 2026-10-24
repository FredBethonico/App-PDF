"""Download de fotos e vídeos de posts públicos do Instagram.

Diferente do resto do pacote, este módulo usa a rede: busca o post pelo link
e baixa as mídias para a memória. Continua sem Streamlit e sem tocar no disco.

O Instagram muda a API sem aviso e limita acessos vindos de servidores
(o Streamlit Cloud incluso). Por isso todo erro conhecido vira uma
`ErroInstagram` com mensagem em português, em vez de traceback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import instaloader
import requests
from instaloader import exceptions as ie

from .util import Arquivo, nome_seguro, numerar

# Um reel longo em boa qualidade fica bem abaixo disso; acima, a memória do
# plano gratuito do Streamlit (1 GB) começa a correr risco.
LIMITE_POR_ARQUIVO = 250 * 1024 * 1024

_LINK_POST = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/"
    r"(?:[A-Za-z0-9_.]+/)?(?:p|reels?|tv)/([A-Za-z0-9_-]{5,})",
    re.IGNORECASE,
)
_LINK_INSTAGRAM = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|instagr\.am)(/|$)", re.IGNORECASE
)
_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
_PEDACO = 1024 * 1024

_MSG_LIMITE = (
    "O Instagram está limitando os acessos vindos deste servidor. "
    "Espere alguns minutos e tente de novo."
)
_MSG_NAO_ACHEI = (
    "O Instagram não entregou esse post. Ele pode ter sido apagado, ser de uma "
    "conta privada ou o Instagram pode estar bloqueando o acesso sem login."
)


class ErroInstagram(ValueError):
    """Link inválido ou recusa do Instagram, já com mensagem legível."""


@dataclass
class Midia:
    url: str
    video: bool


@dataclass
class Post:
    shortcode: str
    autor: str
    legenda: str
    data: datetime | None
    midias: list[Midia]

    @property
    def fotos(self) -> int:
        return sum(1 for midia in self.midias if not midia.video)

    @property
    def videos(self) -> int:
        return sum(1 for midia in self.midias if midia.video)


def extrair_shortcode(link: str) -> str:
    """'https://www.instagram.com/reel/C9xYz12AbcD/?igsh=...' -> 'C9xYz12AbcD'.

    Aceita post (/p/), reel (/reel/, /reels/), IGTV (/tv/), com ou sem o
    nome do perfil antes, com ou sem https e parâmetros de compartilhamento.
    """
    link = (link or "").strip()
    if not link:
        raise ErroInstagram("Cole o link de um post ou reel do Instagram.")
    achado = _LINK_POST.match(link)
    if achado:
        return achado.group(1)
    if not _LINK_INSTAGRAM.match(link):
        raise ErroInstagram("Esse link não é do Instagram.")
    if "/stories/" in link.lower():
        raise ErroInstagram("Stories só aparecem com login e não são suportados aqui.")
    raise ErroInstagram(
        "Esse link parece ser de um perfil ou de outra página. "
        "Cole o link de um post ou reel (ele tem /p/ ou /reel/ no meio)."
    )


# --------------------------------------------------------------------------
# Leitura do post
# --------------------------------------------------------------------------


class _SemEspera(instaloader.RateController):
    """O instaloader dorme minutos quando o Instagram limita os acessos.

    Numa página web isso parece travamento; melhor avisar na hora.
    """

    def sleep(self, secs: float) -> None:
        if secs > 2:
            raise ErroInstagram(_MSG_LIMITE)
        super().sleep(secs)


def _novo_loader(sessao: dict | None) -> instaloader.Instaloader:
    loader = instaloader.Instaloader(
        sleep=False,
        quiet=True,
        user_agent=_NAVEGADOR,
        max_connection_attempts=1,
        request_timeout=30,
        rate_controller=lambda contexto: _SemEspera(contexto),
    )
    if sessao and sessao.get("sessionid"):
        cookies = {chave: str(valor) for chave, valor in sessao.items() if chave != "usuario"}
        cookies.setdefault("csrftoken", "")  # o instaloader exige a chave
        loader.load_session(str(sessao.get("usuario") or "conta"), cookies)
    return loader


def _buscar_post(shortcode: str, sessao: dict | None):
    """Metadados do post pelo instaloader. Separado para os testes trocarem."""
    loader = _novo_loader(sessao)
    return instaloader.Post.from_shortcode(loader.context, shortcode)


def _traduzir(erro: Exception, logado: bool) -> ErroInstagram:
    texto = str(erro)
    dica = "" if logado else (
        " Se isso se repetir, dá para configurar uma sessão do Instagram nos "
        "secrets do app (veja a ajuda no fim da página)."
    )
    if isinstance(erro, ie.PrivateProfileNotFollowedException):
        return ErroInstagram("Esse post é de uma conta privada.")
    if isinstance(erro, ie.LoginRequiredException) or "login" in texto.lower():
        return ErroInstagram("O Instagram pediu login para mostrar esse post." + dica)
    if isinstance(erro, ie.TooManyRequestsException) or any(
        marca in texto for marca in ("429", "401", "Please wait")
    ):
        return ErroInstagram(_MSG_LIMITE + dica)
    if isinstance(erro, (ie.QueryReturnedNotFoundException, ie.BadResponseException)):
        return ErroInstagram(_MSG_NAO_ACHEI + dica)
    if isinstance(erro, ie.QueryReturnedForbiddenException):
        return ErroInstagram("O Instagram recusou o acesso (403)." + dica)
    if isinstance(erro, KeyError):
        return ErroInstagram(
            "O Instagram respondeu num formato que eu não conheço — a API dele pode "
            "ter mudado. Tente de novo mais tarde."
        )
    if isinstance(erro, requests.RequestException):
        return ErroInstagram("Não consegui falar com o Instagram. Confira a conexão e tente de novo.")
    return ErroInstagram(f"O Instagram recusou o pedido: {texto}")


def _midias(post) -> list[Midia]:
    if post.typename == "GraphSidecar":
        return [
            Midia(no.video_url if no.is_video else no.display_url, no.is_video)
            for no in post.get_sidecar_nodes()
        ]
    if post.is_video:
        return [Midia(post.video_url or "", True)]
    return [Midia(post.url, False)]


def ler_post(link: str, *, sessao: dict | None = None) -> Post:
    """Descobre autor, legenda e o endereço de cada foto/vídeo do post.

    `sessao` são os cookies de uma conta logada (pelo menos `sessionid`).
    Sem ela, só posts públicos, e o Instagram às vezes recusa mesmo assim.
    """
    shortcode = extrair_shortcode(link)
    logado = bool(sessao and sessao.get("sessionid"))
    try:
        post = _buscar_post(shortcode, sessao)
        midias = _midias(post)
        autor = post.owner_username or "instagram"
        legenda = post.caption or ""
        data = post.date_utc
    except ErroInstagram:
        raise
    except (ie.InstaloaderException, requests.RequestException, KeyError) as erro:
        raise _traduzir(erro, logado) from erro

    midias = [midia for midia in midias if midia.url]
    if not midias:
        raise ErroInstagram("O post não tem nenhuma foto ou vídeo que eu consiga baixar.")
    return Post(shortcode, autor, legenda, data, midias)


# --------------------------------------------------------------------------
# Download das mídias
# --------------------------------------------------------------------------


def _buscar(url: str) -> bytes:
    """Baixa um arquivo da CDN do Instagram, respeitando o limite de tamanho."""
    try:
        with requests.get(
            url, stream=True, timeout=30, headers={"User-Agent": _NAVEGADOR}
        ) as resposta:
            if resposta.status_code == 403:
                raise ErroInstagram("o link da mídia expirou; busque o post de novo")
            resposta.raise_for_status()
            partes, total = [], 0
            for pedaco in resposta.iter_content(_PEDACO):
                total += len(pedaco)
                if total > LIMITE_POR_ARQUIVO:
                    raise ErroInstagram(
                        f"passa de {LIMITE_POR_ARQUIVO // (1024 * 1024)} MB, grande demais para o servidor"
                    )
                partes.append(pedaco)
    except requests.RequestException as erro:
        raise ErroInstagram(f"falha na conexão ({erro.__class__.__name__})") from erro
    return b"".join(partes)


def extensao(dados: bytes, video: bool) -> str:
    """Extensão pelo conteúdo: a CDN às vezes entrega WEBP ou HEIC num link '.jpg'."""
    if dados[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return ".webp"
    if dados[4:8] == b"ftyp":
        marca = dados[8:12]
        if marca in (b"heic", b"heix", b"mif1"):
            return ".heic"
        if marca == b"avif":
            return ".avif"
        return ".mp4"
    return ".mp4" if video else ".jpg"


def baixar_midias(post: Post, *, progresso=None) -> tuple[list[Arquivo], list[str]]:
    """Baixa todas as mídias do post. Devolve (arquivos, problemas).

    Num carrossel, um item que falhar vira uma linha em `problemas` em vez de
    derrubar os outros.
    """
    prontos: list[Arquivo] = []
    problemas: list[str] = []
    total = len(post.midias)
    for posicao, midia in enumerate(post.midias, start=1):
        rotulo = f"{post.autor}-{post.shortcode}"
        if total > 1:
            rotulo += f"-{numerar(posicao, total)}"
        try:
            dados = _buscar(midia.url)
        except ErroInstagram as erro:
            problemas.append(f"item {posicao} ({erro})")
        else:
            prontos.append((nome_seguro(rotulo) + extensao(dados, midia.video), dados))
        if progresso:
            progresso(posicao / total)
    return prontos, problemas
