"""Dublê do YouTube, para os testes rodarem sem internet.

Troca só a leitura dos metadados (`_extrair_info`). O download continua sendo
o yt-dlp de verdade — com o ffmpeg juntando vídeo e áudio —, só que os
formatos apontam para arquivos locais (file://) gerados aqui com o PyAV.
"""

from __future__ import annotations

import copy
import io
import os
import tempfile
from fractions import Fraction
from pathlib import Path

import av
import yt_dlp
from yt_dlp.utils import DownloadError

import pdf_tools.youtube as yt

PASTA = Path(tempfile.gettempdir()) / "youtube_falso"
SEGUNDOS = 2


def _so_video(caminho: Path) -> None:
    with av.open(str(caminho), "w", format="mp4") as saida:
        faixa = saida.add_stream("libx264", rate=30)
        faixa.width, faixa.height, faixa.pix_fmt = 320, 240, "yuv420p"
        for i in range(30 * SEGUNDOS):
            quadro = av.VideoFrame(320, 240, "yuv420p")
            for plano in quadro.planes:
                plano.update(bytes([(i * 4) % 256]) * plano.buffer_size)
            for pacote in faixa.encode(quadro):
                saida.mux(pacote)
        for pacote in faixa.encode(None):
            saida.mux(pacote)


def _so_audio(caminho: Path) -> None:
    import numpy as np

    taxa = 44100
    with av.open(str(caminho), "w", format="mp4") as saida:
        faixa = saida.add_stream("aac", rate=taxa)
        faixa.layout = "stereo"
        amostras = 1024
        for i in range(taxa * SEGUNDOS // amostras):
            t = (np.arange(amostras) + i * amostras) / taxa
            onda = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
            quadro = av.AudioFrame.from_ndarray(np.stack([onda, onda]), format="fltp", layout="stereo")
            quadro.sample_rate = taxa
            quadro.pts = i * amostras
            quadro.time_base = Fraction(1, taxa)
            for pacote in faixa.encode(quadro):
                saida.mux(pacote)
        for pacote in faixa.encode(None):
            saida.mux(pacote)


def _preparar() -> tuple[Path, Path]:
    PASTA.mkdir(exist_ok=True)
    video, audio = PASTA / "video.mp4", PASTA / "audio.m4a"
    if not video.exists():
        _so_video(video)
    if not audio.exists():
        _so_audio(audio)
    return video, audio


def _info(video_id: str, titulo: str, formatos: list[dict], **extra) -> dict:
    return {
        "id": video_id,
        "title": titulo,
        "uploader": "Canal de Teste",
        "duration": SEGUNDOS,
        "thumbnail": "",
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "formats": formatos,
        **extra,
    }


def infos() -> dict[str, dict]:
    video, audio = _preparar()
    v_tam, a_tam = os.path.getsize(video), os.path.getsize(audio)
    comum_v = {"ext": "mp4", "acodec": "none", "protocol": "file", "url": video.as_uri()}
    formatos = [
        # Dois codecs na mesma altura: tem que preferir o H.264.
        {**comum_v, "format_id": "248", "vcodec": "vp9", "height": 1080, "fps": 30, "tbr": 9000},
        {**comum_v, "format_id": "137", "vcodec": "avc1.640028", "height": 1080, "fps": 30, "tbr": 4000},
        {**comum_v, "format_id": "136", "vcodec": "avc1.4d401f", "height": 720, "fps": 30, "filesize": v_tam},
        {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160,
         "protocol": "file", "url": audio.as_uri()},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128,
         "filesize": a_tam, "protocol": "file", "url": audio.as_uri()},
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2",
         "height": 360, "fps": 30, "tbr": 500, "protocol": "file", "url": video.as_uri()},
        {"format_id": "sb0", "ext": "mhtml", "protocol": "mhtml", "url": "https://x/sb"},
    ]
    # Na segunda extração (a do download) o YouTube devolveu outros IDs.
    trocados = [{**f, "format_id": f["format_id"] + "x"} for f in formatos]
    return {
        "dQw4w9WgXcQ": _info("dQw4w9WgXcQ", "Vídeo de teste: 1/2", formatos),
        "IdsMudaram1": _info("IdsMudaram1", "IDs mudaram", formatos),
        "IdsMudaram1/download": _info("IdsMudaram1", "IDs mudaram", trocados),
        "AoVivo12345": _info("AoVivo12345", "Ao vivo", formatos, is_live=True, live_status="is_live"),
    }


ERROS = {
    "Robozinho01": "ERROR: [youtube] Robozinho01: Sign in to confirm you’re not a bot. "
                   "Use --cookies-from-browser or --cookies for the authentication.",
    "Privado1234": "ERROR: [youtube] Privado1234: Private video. Sign in if you've been granted access",
    "Sumiu123456": "ERROR: [youtube] Sumiu123456: Video unavailable. This video has been removed",
    "Idade123456": "ERROR: [youtube] Idade123456: Sign in to confirm your age.",
}


def instalar() -> None:
    """Imita o yt-dlp de verdade: a busca devolve a info já processada (com
    IDs renomeados, seleção padrão etc.) e o download extrai tudo de novo."""
    tabela = infos()
    yt._OPCOES_EXTRA["enable_file_urls"] = True  # libera os links file:// acima

    def extrair_info(link, opcoes):
        video_id = link.rsplit("=", 1)[-1]
        if video_id in ERROS:
            raise DownloadError(ERROS[video_id])
        with yt_dlp.YoutubeDL({**opcoes, "simulate": True}) as ydl:
            processada = ydl.process_ie_result(copy.deepcopy(tabela[video_id]), download=False)
            return ydl.sanitize_info(processada)

    def executar_download(ydl, link, info):
        video_id = link.rsplit("=", 1)[-1]
        bruta = tabela.get(f"{video_id}/download") or tabela[video_id]
        ydl.process_ie_result(copy.deepcopy(bruta), download=True)

    yt._extrair_info = extrair_info
    yt._executar_download = executar_download


def streams(dados: bytes) -> tuple[int, int]:
    """(faixas de vídeo, faixas de áudio) de um arquivo."""
    with av.open(io.BytesIO(dados)) as container:
        return len(container.streams.video), len(container.streams.audio)
