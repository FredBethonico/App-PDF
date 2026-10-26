"""Extração do áudio de vídeos (MP4 e afins) para MP3.

Usa o PyAV, que traz o ffmpeg e o codificador MP3 dentro do próprio pacote:
não precisa instalar nada no sistema e tudo acontece na memória.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import av

from .util import Arquivo, nome_base, nome_seguro

FORMATOS_VIDEO = ["mp4", "m4v", "mov", "m4a", "webm", "mkv", "avi", "3gp"]
BITRATES = (128, 192, 256, 320)  # kbps

# O MP3 só aceita estas taxas de amostragem; fora delas, reamostra para 44,1 kHz.
_TAXAS_MP3 = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
_TAXA_PADRAO = 44100


@dataclass
class InfoAudio:
    duracao: float  # segundos
    canais: int
    taxa: int  # Hz
    codec: str


def _abrir(dados: bytes):
    try:
        return av.open(io.BytesIO(dados))
    except av.error.FFmpegError as erro:
        raise ValueError("não consegui ler este arquivo como vídeo ou áudio") from erro


def _faixa_de_audio(container):
    if not container.streams.audio:
        raise ValueError("o arquivo não tem faixa de som")
    return container.streams.audio[0]


def _duracao(container, faixa) -> float:
    if faixa.duration and faixa.time_base:
        return float(faixa.duration * faixa.time_base)
    if container.duration:
        return container.duration / av.time_base
    return 0.0


def info_audio(dados: bytes) -> InfoAudio:
    """Duração e formato da faixa de som, sem decodificar nada."""
    with _abrir(dados) as container:
        faixa = _faixa_de_audio(container)
        return InfoAudio(
            duracao=_duracao(container, faixa),
            canais=faixa.codec_context.channels or 2,
            taxa=faixa.codec_context.sample_rate or _TAXA_PADRAO,
            codec=faixa.codec_context.name,
        )


def ler_tempo(texto: str) -> float | None:
    """'1:23' -> 83.0; '1:02:03' -> 3723.0; '90' -> 90.0; em branco -> None."""
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        return None
    if not re.fullmatch(r"\d+(\.\d+)?(:\d{1,2}(\.\d+)?){0,2}", texto):
        raise ValueError(f"Não entendi o tempo '{texto}'. Use segundos (90) ou minutos:segundos (1:30).")
    segundos = 0.0
    for parte in texto.split(":"):
        segundos = segundos * 60 + float(parte)
    return segundos


def formatar_tempo(segundos: float) -> str:
    """83.4 -> '1:23'; 3723 -> '1:02:03'."""
    total = int(round(segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{segs:02d}" if horas else f"{minutos}:{segs:02d}"


def _validar(bitrate: int, inicio: float | None, fim: float | None) -> None:
    if bitrate not in BITRATES:
        raise ValueError(f"Qualidade inválida: {bitrate} kbps.")
    if inicio is not None and inicio < 0:
        raise ValueError("O início do trecho não pode ser negativo.")
    if inicio is not None and fim is not None and fim <= inicio:
        raise ValueError("O fim do trecho precisa vir depois do início.")


def converter_para_mp3(
    dados: bytes,
    *,
    bitrate: int = 192,
    mono: bool = False,
    inicio: float | None = None,
    fim: float | None = None,
) -> bytes:
    """Extrai a faixa de som e devolve um MP3.

    `inicio`/`fim` em segundos cortam um trecho (precisão de ~25 ms, o tamanho
    de um quadro de áudio). `mono` mistura os canais: o arquivo fica com
    metade do tamanho, bom para fala.
    """
    _validar(bitrate, inicio, fim)
    inicio = inicio or 0.0

    with _abrir(dados) as entrada:
        faixa = _faixa_de_audio(entrada)
        duracao = _duracao(entrada, faixa)
        if duracao and inicio >= duracao:
            raise ValueError(
                f"o início ({formatar_tempo(inicio)}) passa da duração ({formatar_tempo(duracao)})"
            )
        taxa = faixa.codec_context.sample_rate or _TAXA_PADRAO
        if taxa not in _TAXAS_MP3:
            taxa = _TAXA_PADRAO

        buffer = io.BytesIO()
        with av.open(buffer, "w", format="mp3") as saida:
            destino = saida.add_stream("libmp3lame", rate=taxa)
            destino.layout = "mono" if mono or faixa.codec_context.channels == 1 else "stereo"
            destino.bit_rate = bitrate * 1000

            if inicio:
                # Pula direto para perto do início em vez de decodificar tudo antes.
                entrada.seek(int(inicio * av.time_base), backward=True)

            escreveu = False
            try:
                for quadro in entrada.decode(faixa):
                    if quadro.pts is not None:
                        momento = float(quadro.pts * quadro.time_base)
                        if momento + quadro.samples / quadro.sample_rate <= inicio:
                            continue
                        if fim is not None and momento >= fim:
                            break
                    quadro.pts = None  # o trecho cortado recomeça do zero
                    for pacote in destino.encode(quadro):
                        saida.mux(pacote)
                    escreveu = True
            except av.error.InvalidDataError:
                # Vídeo truncado no fim (download interrompido): fica com o que deu.
                if not escreveu:
                    raise ValueError("a faixa de som está corrompida") from None
            for pacote in destino.encode(None):
                saida.mux(pacote)

    if not escreveu:
        raise ValueError("o trecho escolhido não tem som")
    return buffer.getvalue()


def converter_lote(
    arquivos: list[Arquivo], *, progresso=None, **opcoes
) -> tuple[list[Arquivo], list[str]]:
    """Converte vários vídeos com as mesmas opções. Devolve (prontos, problemas).

    Um arquivo ruim vira uma linha em `problemas` em vez de derrubar o lote;
    opções inválidas levantam erro antes de começar, porque valem para todos.
    """
    if not arquivos:
        raise ValueError("Envie pelo menos um vídeo.")
    _validar(opcoes.get("bitrate", 192), opcoes.get("inicio"), opcoes.get("fim"))

    prontos: list[Arquivo] = []
    problemas: list[str] = []
    for posicao, (nome, dados) in enumerate(arquivos, start=1):
        try:
            mp3 = converter_para_mp3(dados, **opcoes)
        except ValueError as erro:
            problemas.append(f"{nome} ({erro})")
        except av.error.FFmpegError as erro:
            problemas.append(f"{nome} (erro do ffmpeg: {erro.strerror or erro})")
        else:
            prontos.append((nome_seguro(nome_base(nome)) + ".mp3", mp3))
        if progresso:
            progresso(posicao / len(arquivos))
    return prontos, problemas
