"""Dublê da rede do Instagram, para os testes rodarem sem internet.

Troca as duas funções de `pdf_tools.instagram` que saem para a rede:
a que lê o post pelo instaloader e a que baixa da CDN.
"""

from __future__ import annotations

import io
from datetime import datetime
from types import SimpleNamespace

from instaloader import exceptions as ie
from PIL import Image

import pdf_tools.instagram as ig


def jpeg(cor=(200, 80, 40), tamanho=(320, 320)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(buffer, "JPEG")
    return buffer.getvalue()


def webp(cor=(40, 80, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), cor).save(buffer, "WEBP")
    return buffer.getvalue()


MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 256

CDN = {
    "https://cdn.falso/a.jpg": jpeg(),
    "https://cdn.falso/b.mp4": MP4,
    "https://cdn.falso/c.jpg": webp(),  # extensão errada de propósito
    "https://cdn.falso/foto.jpg": jpeg((10, 160, 90)),
    "https://cdn.falso/reel.mp4": MP4,
}


def _no(url: str, video: bool) -> SimpleNamespace:
    return SimpleNamespace(
        is_video=video, display_url=url if not video else "https://cdn.falso/capa.jpg",
        video_url=url if video else None,
    )


def _post(typename: str, *, url="", video_url=None, nos=(), autor="fulano", legenda=""):
    return SimpleNamespace(
        typename=typename,
        owner_username=autor,
        caption=legenda,
        date_utc=datetime(2026, 5, 1, 12, 0),
        url=url,
        is_video=video_url is not None,
        video_url=video_url,
        get_sidecar_nodes=lambda: list(nos),
    )


POSTS = {
    "CARROSSEL1": _post(
        "GraphSidecar",
        nos=[_no("https://cdn.falso/a.jpg", False), _no("https://cdn.falso/b.mp4", True),
             _no("https://cdn.falso/c.jpg", False)],
        legenda="Três itens de teste",
    ),
    "FOTO123456": _post("GraphImage", url="https://cdn.falso/foto.jpg", autor="beltrana"),
    "REEL123456": _post("GraphVideo", url="https://cdn.falso/capa.jpg",
                        video_url="https://cdn.falso/reel.mp4"),
    "MEIOQUEBRADO": _post(
        "GraphSidecar",
        nos=[_no("https://cdn.falso/a.jpg", False), _no("https://cdn.falso/sumiu.jpg", False)],
    ),
}

ERROS = {
    "SUMIU12345": ie.BadResponseException("Fetching Post metadata failed."),
    "LIMITE1234": ie.ConnectionException(
        'JSON Query to graphql/query: 401 Unauthorized - "fail" status, message '
        '"Please wait a few minutes before you try again."'
    ),
    "LOGIN12345": ie.LoginRequiredException("Redirected to login page. Use --login or --load-cookies."),
    "MUDOU12345": KeyError("xdt_shortcode_media"),
}


def instalar() -> None:
    def buscar_post(shortcode, sessao):
        if shortcode in ERROS:
            raise ERROS[shortcode]
        return POSTS[shortcode]

    def buscar(url):
        if url not in CDN:
            raise ig.ErroInstagram("HTTP 404")
        return CDN[url]

    ig._buscar_post = buscar_post
    ig._buscar = buscar
