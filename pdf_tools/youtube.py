"""Download de vídeos do YouTube, com escolha de qualidade e estimativa de tamanho.

Adaptado do script de linha de comando `yt_baixar.py`. Como o módulo do
Instagram, este usa a rede, mas não importa Streamlit. A diferença: o yt-dlp
só sabe gravar em disco (e o ffmpeg precisa de arquivos para juntar vídeo e
áudio), então o download acontece numa pasta temporária que é apagada logo
depois de o resultado ser lido para a memória.

Dependências, todas pacotes Python (nada para instalar no sistema):
    yt-dlp[default]  o downloader
    imageio-ffmpeg   traz um executável do ffmpeg (junta vídeo + áudio)
    deno             runtime JS que o yt-dlp usa para liberar os formatos do YouTube

Sem ffmpeg, só sobram os formatos que já vêm com som (em geral 360p).
Sem runtime JS, algumas qualidades somem da lista.
"""

from __future__ import annotations

import copy
import functools
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

import yt_dlp
from yt_dlp.utils import DownloadError

from .util import Arquivo, nome_seguro

# O arquivo inteiro fica na memória do servidor (sessão + botão de download).
# 900 MB deixa passar 720p de vídeos longos, mas é apertado no Streamlit
# Cloud: dois downloads grandes ao mesmo tempo podem estourar a memória e
# reiniciar o app. Se isso acontecer, baixe este número.
LIMITE_YOUTUBE = 900 * 1024 * 1024
BITRATE_MP3 = 192  # kbps da opção "só áudio em MP3"

_ID = r"([A-Za-z0-9_-]{11})"
_HOSTS = r"(?:https?://)?(?:(?:www|m|music)\.)?(?:youtube\.com|youtube-nocookie\.com)"
_LINK_VIDEO = [
    re.compile(_HOSTS + r"/watch/?\?(?:.*&)?v=" + _ID, re.IGNORECASE),
    re.compile(_HOSTS + r"/(?:shorts|live|embed|v|e)/" + _ID, re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?youtu\.be/" + _ID, re.IGNORECASE),
]
_LINK_YOUTUBE = re.compile(
    r"^(?:https?://)?(?:(?:www|m|music)\.)?(?:youtube\.com|youtube-nocookie\.com|youtu\.be)(/|$)",
    re.IGNORECASE,
)

_MSG_ROBO = (
    "O YouTube pediu para provar que não é um robô — ele costuma fazer isso com "
    "pedidos vindos de servidores na nuvem."
)
_DICA_COOKIES = (
    " Se isso se repetir, dá para configurar cookies de uma conta do YouTube nos "
    "secrets do app (veja a ajuda no fim da página)."
)


class ErroYoutube(ValueError):
    """Link inválido ou recusa do YouTube, já com mensagem legível."""


@dataclass
class Opcao:
    """Uma linha da tabela de qualidades."""

    rotulo: str
    altura: int  # 0 = só áudio
    fps: int
    codec: str
    seletor: str  # formato do yt-dlp ('137+140', '18' ...)
    bytes: float | None
    aprox: bool  # True = estimativa por bitrate
    so_audio: bool = False
    mp3: bool = False  # converte o áudio para MP3 depois de baixar

    @property
    def extensao(self) -> str:
        if self.mp3:
            return ".mp3"
        return ".m4a" if self.so_audio else ".mp4"


@dataclass
class Video:
    id: str
    titulo: str
    canal: str
    duracao: int  # segundos
    miniatura: str
    opcoes: list[Opcao]
    info: dict = field(repr=False, default_factory=dict)  # info do yt-dlp, para não buscar de novo

    @property
    def link(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def extrair_id(link: str) -> str:
    """'https://youtu.be/dQw4w9WgXcQ?si=...' -> 'dQw4w9WgXcQ'.

    Aceita watch?v=, youtu.be/, /shorts/, /live/ e /embed/, com ou sem https,
    em www, m. ou music. Parâmetros extras (tempo, playlist) são ignorados.
    """
    link = (link or "").strip()
    if not link:
        raise ErroYoutube("Cole o link de um vídeo do YouTube.")
    for padrao in _LINK_VIDEO:
        achado = padrao.match(link)
        if achado:
            return achado.group(1)
    if not _LINK_YOUTUBE.match(link):
        raise ErroYoutube("Esse link não é do YouTube.")
    if "list=" in link:
        raise ErroYoutube(
            "Esse link é de uma playlist. Abra um dos vídeos e copie o link dele."
        )
    raise ErroYoutube(
        "Esse link parece ser de um canal ou de outra página. Cole o link de um "
        "vídeo (ele tem watch?v=, youtu.be/ ou /shorts/)."
    )


# --------------------------------------------------------------------------
# Ferramentas externas (ffmpeg e runtime JS), todas vindas de pacotes pip
# --------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def ferramentas() -> tuple[str | None, dict]:
    """(caminho do ffmpeg ou None, runtimes JS no formato do yt-dlp)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # pacote ausente ou sem binário para a plataforma
            ffmpeg = None

    deno_bin = None
    try:
        import deno

        deno_bin = deno.find_deno_bin()
    except Exception:
        deno_bin = None
    deno_bin = deno_bin or shutil.which("deno")
    if deno_bin:
        return ffmpeg, {"deno": {"path": deno_bin}}
    if shutil.which("node"):
        return ffmpeg, {"node": {"path": shutil.which("node")}}
    return ffmpeg, {}


# Opções extras do yt-dlp; os testes usam para liberar links file://.
_OPCOES_EXTRA: dict = {}


def _opcoes_base(cookies: str | None, pasta: str) -> dict:
    ffmpeg, runtimes = ferramentas()
    opcoes = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": False,
        "paths": {"home": pasta, "temp": pasta},
    }
    if ffmpeg:
        opcoes["ffmpeg_location"] = ffmpeg
    if runtimes:
        opcoes["js_runtimes"] = runtimes
    if cookies:
        arquivo = os.path.join(pasta, "cookies.txt")
        with open(arquivo, "w", encoding="utf-8") as saida:
            saida.write(cookies.strip() + "\n")
        opcoes["cookiefile"] = arquivo
    opcoes.update(_OPCOES_EXTRA)
    return opcoes


def _traduzir(erro: Exception, com_cookies: bool) -> ErroYoutube:
    texto = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?([A-Za-z0-9_-]{11}:\s*)?", "", str(erro)).strip()
    baixo = texto.lower()
    dica = "" if com_cookies else _DICA_COOKIES
    if "confirm your age" in baixo or "age-restricted" in baixo or "inappropriate for some users" in baixo:
        return ErroYoutube("O vídeo tem restrição de idade e só abre com login." + dica)
    if "not a bot" in baixo or "sign in to confirm you" in baixo:
        return ErroYoutube(_MSG_ROBO + dica)
    if "private video" in baixo:
        return ErroYoutube("Esse vídeo é privado.")
    if "members" in baixo and ("join" in baixo or "only" in baixo):
        return ErroYoutube("Esse vídeo é exclusivo para membros do canal.")
    if "premieres in" in baixo or "live event will begin" in baixo or "upcoming" in baixo:
        return ErroYoutube("Esse vídeo ainda não estreou.")
    if "429" in baixo or "too many requests" in baixo:
        return ErroYoutube(
            "O YouTube está limitando os acessos vindos deste servidor. Espere alguns "
            "minutos e tente de novo." + dica
        )
    if "video unavailable" in baixo or "has been removed" in baixo or "not available" in baixo:
        return ErroYoutube(
            "O YouTube diz que esse vídeo não está disponível (apagado, bloqueado no "
            "país do servidor ou com link errado)."
        )
    if any(marca in baixo for marca in (
        "unable to connect", "timed out", "name or service", "connection", "proxy",
    )):
        return ErroYoutube("Não consegui falar com o YouTube. Confira a conexão e tente de novo.")
    return ErroYoutube(f"O YouTube recusou o pedido: {texto[:300]}")


# --------------------------------------------------------------------------
# Formatos e estimativa de tamanho
# --------------------------------------------------------------------------


def tamanho_formato(fmt: dict, duracao: float) -> tuple[float | None, bool]:
    """(bytes, aproximado?). Exato quando o YouTube informa; senão, pelo bitrate."""
    if fmt.get("filesize"):
        return fmt["filesize"], False
    if fmt.get("filesize_approx"):
        return fmt["filesize_approx"], True
    tbr = fmt.get("tbr") or ((fmt.get("vbr") or 0) + (fmt.get("abr") or 0))
    if tbr and duracao:
        return tbr * 1000 / 8 * duracao, True  # tbr em kbit/s
    return None, True


def _tem(valor) -> bool:
    return valor not in (None, "none")


def montar_opcoes(info: dict, tem_ffmpeg: bool) -> list[Opcao]:
    """Uma opção por altura+fps (a melhor de cada), mais as de só áudio.

    Com ffmpeg: vídeo sem som + melhor áudio, juntados num MP4. Prefere H.264
    porque abre em qualquer player. Sem ffmpeg: só formatos que já têm som.
    """
    duracao = info.get("duration") or 0
    formatos = [f for f in info.get("formats") or [] if f.get("protocol") != "mhtml"]
    audios = [f for f in formatos if _tem(f.get("acodec")) and not _tem(f.get("vcodec"))]
    # m4a (AAC) cabe no MP4 sem conversão; opus só em último caso.
    melhor_audio = (
        max(audios, key=lambda f: (f.get("ext") == "m4a", f.get("abr") or 0)) if audios else None
    )
    opcoes: list[Opcao] = []

    if tem_ffmpeg and melhor_audio:
        a_tam, a_aprox = tamanho_formato(melhor_audio, duracao)
        grupos: dict[tuple[int, int], list[dict]] = {}
        for f in formatos:
            if _tem(f.get("vcodec")) and not _tem(f.get("acodec")) and f.get("height"):
                grupos.setdefault((f["height"], round(f.get("fps") or 0)), []).append(f)
        for (altura, fps), candidatos in sorted(grupos.items(), reverse=True):
            v = max(
                candidatos,
                key=lambda f: ((f.get("vcodec") or "").startswith("avc1"), f.get("tbr") or 0),
            )
            v_tam, v_aprox = tamanho_formato(v, duracao)
            opcoes.append(Opcao(
                rotulo=f"{altura}p",
                altura=altura,
                fps=fps,
                codec=(v.get("vcodec") or "?").split(".")[0],
                seletor=f"{v['format_id']}+{melhor_audio['format_id']}",
                bytes=(v_tam + (a_tam or 0)) if v_tam else None,
                aprox=v_aprox or a_aprox,
            ))
    else:
        completos = [f for f in formatos if _tem(f.get("acodec")) and _tem(f.get("vcodec"))]
        # Sem ffmpeg não dá para converter: só MP4 que já vem pronto.
        completos = [f for f in completos if f.get("ext") == "mp4"] or completos
        for f in sorted(completos, key=lambda f: f.get("height") or 0, reverse=True):
            tam, aprox = tamanho_formato(f, duracao)
            opcoes.append(Opcao(
                rotulo=f"{f.get('height') or '?'}p",
                altura=f.get("height") or 0,
                fps=round(f.get("fps") or 0),
                codec=(f.get("vcodec") or "?").split(".")[0],
                seletor=f["format_id"],
                bytes=tam,
                aprox=aprox,
            ))

    if melhor_audio:
        a_tam, a_aprox = tamanho_formato(melhor_audio, duracao)
        codec = (melhor_audio.get("acodec") or "?").split(".")[0]
        kbps = round(melhor_audio.get("abr") or 0)
        opcoes.append(Opcao(
            rotulo=f"Só áudio ({melhor_audio.get('ext')}, {kbps} kbps)",
            altura=0, fps=0, codec=codec, seletor=melhor_audio["format_id"],
            bytes=a_tam, aprox=a_aprox, so_audio=True,
        ))
        opcoes.append(Opcao(
            rotulo=f"Só áudio em MP3 ({BITRATE_MP3} kbps)",
            altura=0, fps=0, codec="mp3", seletor=melhor_audio["format_id"],
            bytes=(BITRATE_MP3 * 1000 / 8 * duracao) if duracao else None,
            aprox=True, so_audio=True, mp3=True,
        ))
    return opcoes


def escolher_opcao(opcoes: list[Opcao], qualidade: str | int | None = None) -> Opcao | None:
    """'melhor', 'audio', 'mp3' ou uma altura (1080 -> 1080p ou a mais próxima abaixo)."""
    if not opcoes:
        return None
    videos = [o for o in opcoes if not o.so_audio]
    q = str(qualidade or "melhor").lower().rstrip("p")
    if q == "melhor":
        return videos[0] if videos else opcoes[0]
    if q in ("audio", "áudio"):
        return next((o for o in opcoes if o.so_audio and not o.mp3), None)
    if q == "mp3":
        return next((o for o in opcoes if o.mp3), None)
    if q.isdigit() and videos:
        abaixo = [o for o in videos if o.altura <= int(q)]
        return abaixo[0] if abaixo else videos[-1]
    raise ValueError(f"qualidade inválida: {qualidade!r}")


# --------------------------------------------------------------------------
# Leitura e download
# --------------------------------------------------------------------------


def _extrair_info(link: str, opcoes: dict) -> dict:
    """Metadados pelo yt-dlp, sem baixar. Separado para os testes trocarem."""
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        return ydl.sanitize_info(ydl.extract_info(link, download=False))


def ler_video(link: str, *, cookies: str | None = None) -> Video:
    """Título, canal, duração e a lista de qualidades com tamanho estimado.

    `cookies` é o conteúdo de um cookies.txt (formato Netscape) de uma conta
    logada. Sem ele, só vídeos públicos, e o YouTube às vezes recusa mesmo assim.
    """
    video_id = extrair_id(link)
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="yt_") as pasta:
        try:
            info = _extrair_info(url, _opcoes_base(cookies, pasta))
        except DownloadError as erro:
            raise _traduzir(erro, bool(cookies)) from erro

    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise ErroYoutube("Transmissões ao vivo não dá para baixar enquanto estão no ar.")
    ffmpeg, _ = ferramentas()
    opcoes = montar_opcoes(info, bool(ffmpeg))
    if not opcoes:
        raise ErroYoutube("O YouTube não entregou nenhum formato que eu consiga baixar.")
    return Video(
        id=info.get("id") or video_id,
        titulo=info.get("title") or video_id,
        canal=info.get("uploader") or info.get("channel") or "",
        duracao=int(info.get("duration") or 0),
        miniatura=info.get("thumbnail") or "",
        opcoes=opcoes,
        info=info,
    )


class _Progresso:
    """Junta o progresso das partes (vídeo, depois áudio) numa fração só."""

    def __init__(self, total: float | None, avisar, limite: int):
        self.total = total
        self.avisar = avisar
        self.limite = limite
        self.partes_prontas = 0.0
        self.parte = 1

    def hook(self, d: dict) -> None:
        baixado = d.get("downloaded_bytes") or 0
        if self.partes_prontas + baixado > self.limite:
            raise ErroYoutube(
                f"O arquivo passou de {self.limite // (1024 * 1024)} MB, grande demais para "
                "o servidor. Escolha uma qualidade menor."
            )
        if d["status"] == "finished":
            self.partes_prontas += d.get("total_bytes") or baixado
            self.parte += 1
            return
        if d["status"] != "downloading" or not self.avisar:
            return
        total = self.total or d.get("total_bytes") or d.get("total_bytes_estimate")
        fracao = min((self.partes_prontas + baixado) / total, 1.0) if total else 0.0
        velocidade = d.get("speed")
        texto = f"Baixando parte {self.parte}"
        if velocidade:
            texto += f" — {velocidade / (1024 * 1024):.1f} MB/s".replace(".", ",")
        self.avisar(fracao, texto)

    def pos_processamento(self, d: dict) -> None:
        if d["status"] == "started" and self.avisar:
            nomes = {"Merger": "Juntando vídeo e áudio...", "FFmpegMerger": "Juntando vídeo e áudio..."}
            self.avisar(1.0, nomes.get(d.get("postprocessor"), "Finalizando o arquivo..."))


def _arquivo_final(pasta: str) -> str | None:
    """O maior arquivo de mídia que sobrou na pasta (ignora .part e cookies)."""
    candidatos = [
        os.path.join(pasta, nome) for nome in os.listdir(pasta)
        if not nome.endswith((".part", ".ytdl", ".txt", ".json")) and ".temp." not in nome
    ]
    candidatos = [c for c in candidatos if os.path.isfile(c)]
    return max(candidatos, key=os.path.getsize) if candidatos else None


def baixar(
    video: Video,
    opcao: Opcao,
    *,
    cookies: str | None = None,
    progresso=None,
    limite: int = LIMITE_YOUTUBE,
) -> Arquivo:
    """Baixa a qualidade escolhida e devolve (nome, bytes).

    `progresso(fracao, texto)` é chamado durante o download. Vídeo + áudio
    separados são juntados num MP4 pelo ffmpeg; "só áudio em MP3" é convertido
    pelo PyAV, o mesmo da ferramenta MP4 para MP3.
    """
    if opcao.bytes and not opcao.aprox and opcao.bytes > limite:
        raise ErroYoutube(
            f"Essa qualidade tem {opcao.bytes / (1024 * 1024):.0f} MB, acima do limite de "
            f"{limite // (1024 * 1024)} MB. Escolha uma menor."
        )
    ffmpeg, _ = ferramentas()
    if "+" in opcao.seletor and not ffmpeg:
        raise ErroYoutube("Essa qualidade precisa do ffmpeg, que não está disponível no servidor.")

    acompanhamento = _Progresso(opcao.bytes, progresso, limite)
    with tempfile.TemporaryDirectory(prefix="yt_") as pasta:
        opcoes = _opcoes_base(cookies, pasta)
        opcoes.update({
            "format": opcao.seletor,
            "outtmpl": "video.%(ext)s",
            "progress_hooks": [acompanhamento.hook],
            "postprocessor_hooks": [acompanhamento.pos_processamento],
            "continuedl": False,
        })
        if "+" in opcao.seletor:
            opcoes["merge_output_format"] = "mp4"
        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                ydl.process_ie_result(copy.deepcopy(video.info), download=True)
        except DownloadError as erro:
            raise _traduzir(erro, bool(cookies)) from erro

        caminho = _arquivo_final(pasta)
        if not caminho:
            raise ErroYoutube("O download terminou sem gerar arquivo. Tente de novo.")
        with open(caminho, "rb") as entrada:
            dados = entrada.read()
        extensao = os.path.splitext(caminho)[1].lower() or opcao.extensao

    if opcao.mp3:
        from .audio import converter_para_mp3

        if progresso:
            progresso(1.0, "Convertendo para MP3...")
        dados = converter_para_mp3(dados, bitrate=BITRATE_MP3)
        extensao = ".mp3"

    nome = nome_seguro(f"{nome_seguro(video.titulo)[:100]} [{video.id}]") + extensao
    return nome, dados
