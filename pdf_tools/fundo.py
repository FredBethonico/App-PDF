"""Remoção de fundo de imagem: automática (IA ou cor), retoque a pincel e saída.

O trabalho gira em torno de uma *máscara*: uma imagem em tons de cinza do
tamanho da original, onde 255 = fica e 0 = some. As etapas são independentes
e todas trocam `bytes`, para o Streamlit conseguir guardar cada uma em cache:

    mascara_ia / mascara_por_cor / mascara_vazia    -> máscara automática
    aplicar_pinceladas(máscara, traços do pincel)   -> máscara retocada
    remover_fundo(imagem, máscara, ...)             -> arquivo final

A IA usa o rembg (modelos U2-Net/IS-Net rodando no onnxruntime, na CPU).
O modelo é baixado do GitHub do rembg na primeira vez e fica no disco.
"""

from __future__ import annotations

import io
import threading

import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageFilter, ImageOps

from .redimensionar import LADO_MAXIMO, _modo_de_trabalho

# nome do modelo no rembg -> (rótulo, tamanho do download)
MODELOS_IA = {
    "silueta": ("Rápido", "43 MB"),
    "isnet-general-use": ("Detalhado", "180 MB"),
}
MODELO_PADRAO = "silueta"
FUNDOS_SAIDA = ("transparente", "cor")
FORMATOS_SAIDA = ("PNG", "WEBP", "JPEG")

_EXTENSOES = {"PNG": ".png", "WEBP": ".webp", "JPEG": ".jpg"}
# Os cálculos da máscara usam vários arrays do tamanho da imagem; acima disso
# o plano gratuito do Streamlit (1 GB) não aguenta. 25 MP ~ foto de 6000 x 4000.
MEGAPIXELS_MAXIMO = 25
_DISTANCIA_MAXIMA = 441.67  # sqrt(3 * 255²): do preto ao branco no espaço RGB
_SESSOES: dict = {}
_TRAVA = threading.Lock()


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------


def _abrir(dados: bytes) -> Image.Image:
    """Imagem em RGB ou RGBA, já girada conforme o EXIF do celular."""
    with Image.open(io.BytesIO(dados)) as aberta:
        aberta.load()
        imagem = ImageOps.exif_transpose(aberta)
    if max(imagem.size) > LADO_MAXIMO:
        raise ValueError(
            f"A imagem tem {imagem.width} × {imagem.height} px; o limite é "
            f"{LADO_MAXIMO:,} px por lado. Reduza antes em Redimensionar imagens.".replace(",", ".")
        )
    if imagem.width * imagem.height > MEGAPIXELS_MAXIMO * 1_000_000:
        mp = imagem.width * imagem.height / 1_000_000
        raise ValueError(
            f"A imagem tem {mp:.0f} megapixels; o limite aqui é {MEGAPIXELS_MAXIMO}. "
            "Reduza antes em Redimensionar imagens (6000 px no lado maior já resolve)."
        )
    imagem = _modo_de_trabalho(imagem)
    if imagem.mode == "LA":
        return imagem.convert("RGBA")
    if imagem.mode == "L":
        return imagem.convert("RGB")
    return imagem


def _png(imagem: Image.Image) -> bytes:
    buffer = io.BytesIO()
    imagem.save(buffer, "PNG")
    return buffer.getvalue()


def _ler_mascara(mascara: bytes, tamanho: tuple[int, int]) -> Image.Image:
    with Image.open(io.BytesIO(mascara)) as aberta:
        cinza = aberta.convert("L")
    if cinza.size != tamanho:
        cinza = cinza.resize(tamanho, Image.BILINEAR)
    return cinza


def _borda(rgb: np.ndarray, espessura: int = 3) -> np.ndarray:
    """Pixels da moldura da imagem, num array N x 3."""
    e = max(1, min(espessura, rgb.shape[0] // 2, rgb.shape[1] // 2))
    return np.concatenate(
        [
            rgb[:e].reshape(-1, 3),
            rgb[-e:].reshape(-1, 3),
            rgb[:, :e].reshape(-1, 3),
            rgb[:, -e:].reshape(-1, 3),
        ]
    )


# --------------------------------------------------------------------------
# Análise
# --------------------------------------------------------------------------


def analisar_fundo(dados: bytes) -> tuple[str, float]:
    """(cor mais comum na moldura em #RRGGBB, fração da moldura com essa cor).

    Uma fração alta (acima de ~0,95) indica fundo liso: logo, print, foto de
    produto em estúdio. Aí o método por cor costuma ser mais limpo que a IA.
    """
    rgb = np.asarray(_abrir(dados).convert("RGB"))
    borda = _borda(rgb).astype(np.float32)
    cor = _cor_da_moldura(rgb)
    distancia = np.sqrt(((borda - cor) ** 2).sum(axis=1))
    fracao = float((distancia < 0.08 * _DISTANCIA_MAXIMA).mean())
    hexa = "#{:02X}{:02X}{:02X}".format(*(int(round(c)) for c in cor))
    return hexa, fracao


# --------------------------------------------------------------------------
# Máscaras automáticas
# --------------------------------------------------------------------------


def _sessao(modelo: str):
    """Sessão do rembg, criada uma vez por processo (carregar o modelo leva segundos)."""
    if modelo not in MODELOS_IA:
        raise ValueError(f"Modelo de IA desconhecido: {modelo}.")
    with _TRAVA:
        if modelo not in _SESSOES:
            try:
                import onnxruntime as ort
                from rembg import new_session
            except ImportError as erro:  # pragma: no cover - depende da instalação
                raise ValueError(
                    "A remoção por IA precisa do pacote rembg (pip install \"rembg[cpu]\")."
                ) from erro
            opcoes = ort.SessionOptions()
            # Sem o "arena" o onnxruntime devolve a memória entre uma imagem e
            # outra; com ele, o pico fica preso no processo e o servidor estoura.
            opcoes.enable_cpu_mem_arena = False
            opcoes.intra_op_num_threads = 2
            try:
                _SESSOES[modelo] = new_session(modelo, sess_opts=opcoes)
            except Exception as erro:
                tamanho = MODELOS_IA[modelo][1]
                raise ValueError(
                    f"Não consegui baixar o modelo de IA ({tamanho}). Confira a "
                    f"conexão do servidor ou use o método por cor. Detalhe: {erro}"
                ) from erro
        return _SESSOES[modelo]


def mascara_ia(dados: bytes, modelo: str = MODELO_PADRAO) -> bytes:
    """Máscara feita por IA: acha o objeto principal (pessoa, bicho, produto)."""
    imagem = _abrir(dados)
    from rembg import remove

    mascara = remove(imagem.convert("RGB"), session=_sessao(modelo), only_mask=True)
    return _png(mascara.convert("L"))


def mascara_por_cor(
    dados: bytes,
    *,
    cor: str | None = None,
    tolerancia: float = 12,
    so_pelas_bordas: bool = True,
) -> bytes:
    """Máscara que apaga a cor do fundo.

    cor             - '#RRGGBB'; None usa a cor mais comum na moldura da imagem
    tolerancia      - 0 a 100: quão diferente da cor ainda conta como fundo
    so_pelas_bordas - True apaga só a mancha de fundo ligada às bordas (o branco
                      de dentro de um olho, por exemplo, fica); False apaga a cor
                      em qualquer lugar (útil no miolo das letras de um logo)

    A borda sai suave: cada pixel do contorno recebe a transparência
    proporcional à mistura entre o desenho e o fundo (veja `_refinar_borda`).
    """
    from scipy import ndimage

    tolerancia = float(max(0, min(tolerancia, 100)))
    rgb = np.asarray(_abrir(dados).convert("RGB"))  # uint8: 1/4 da memória do float
    alvo = np.array(ImageColor.getrgb(cor)[:3] if cor else _cor_da_moldura(rgb), np.float32)

    distancia = np.zeros(rgb.shape[:2], np.float32)
    for canal in range(3):  # um canal por vez, para não criar um float32 H x W x 3
        distancia += (rgb[..., canal].astype(np.float32) - alvo[canal]) ** 2
    np.sqrt(distancia, out=distancia)
    distancia *= 100 / _DISTANCIA_MAXIMA

    rampa = max(3.0, tolerancia * 0.5)
    alfa = np.clip((distancia - tolerancia) / rampa, 0, 1)  # 0 = fundo, 1 = fica
    del distancia

    if so_pelas_bordas:
        rotulos, quantos = ndimage.label(alfa < 1)
        moldura = np.concatenate([rotulos[0], rotulos[-1], rotulos[:, 0], rotulos[:, -1]])
        ligado = np.zeros(quantos + 1, bool)  # tabela por rótulo: bem mais rápido que np.isin
        ligado[moldura] = True
        ligado[0] = False
        alfa[~ligado[rotulos]] = 1.0
        del rotulos

    _refinar_borda(rgb, alfa, alvo, tolerancia)
    return _png(Image.fromarray((alfa * 255).round().astype(np.uint8), "L"))


def _refinar_borda(rgb: np.ndarray, alfa: np.ndarray, fundo: np.ndarray, tolerancia: float) -> None:
    """Ajusta, no lugar, o alfa dos pixels de contorno pela mistura de cores.

    Num logo com antisserrilhado, o pixel da borda é uma mistura
    C = a·F + (1-a)·B do desenho F com o fundo B. A rampa da tolerância não
    enxerga isso: um pixel 40% fundo fica 100% opaco e vira um halo claro
    quando o logo vai para um fundo escuro. Aqui F é a cor do pixel "cheio"
    mais próximo, e a = projeção de (C - B) sobre (F - B).
    """
    from scipy import ndimage

    removido = alfa < 0.5
    if not removido.any() or removido.all():
        return
    perto_do_fundo = ndimage.binary_dilation(removido, iterations=2)
    nucleo = ndimage.binary_erosion(alfa >= 1, iterations=2)
    faixa = perto_do_fundo & (alfa > 0) & ~nucleo
    if not nucleo.any() or not faixa.any():
        return

    # Só a região em volta da faixa entra na transformada de distância.
    linhas, colunas = np.nonzero(faixa)
    y0, y1 = max(0, linhas.min() - 6), min(alfa.shape[0], linhas.max() + 7)
    x0, x1 = max(0, colunas.min() - 6), min(alfa.shape[1], colunas.max() + 7)
    iy, ix = ndimage.distance_transform_edt(
        ~nucleo[y0:y1, x0:x1], return_distances=False, return_indices=True
    )
    fy, fx = linhas - y0, colunas - x0
    vy, vx = iy[fy, fx], ix[fy, fx]
    perto = (vy - fy) ** 2 + (vx - fx) ** 2 <= 16  # desenho cheio a até 4 px
    if not perto.any():
        return  # traço fino demais para ter "miolo": fica com a rampa

    linhas, colunas = linhas[perto], colunas[perto]
    cor_pixel = rgb[linhas, colunas].astype(np.float32) - fundo
    cor_cheia = rgb[vy[perto] + y0, vx[perto] + x0].astype(np.float32) - fundo
    norma = (cor_cheia ** 2).sum(axis=1)
    minimo = (tolerancia / 100 * _DISTANCIA_MAXIMA) ** 2
    valido = norma > max(minimo, 400)  # desenho quase da cor do fundo: não dá para separar
    mistura = np.clip((cor_pixel * cor_cheia).sum(axis=1) / np.maximum(norma, 1), 0, 1)
    alfa[linhas[valido], colunas[valido]] = mistura[valido]


def _cor_da_moldura(rgb: np.ndarray) -> np.ndarray:
    """Média do grupo de cor mais comum na moldura.

    Agrupa em faixas de 16 tons para juntar o "quase branco" com o branco.
    """
    borda = _borda(rgb).astype(np.float32)
    faixas = (borda // 16).astype(np.int32)
    codigos = faixas[:, 0] * 256 + faixas[:, 1] * 16 + faixas[:, 2]
    valores, contagens = np.unique(codigos, return_counts=True)
    return borda[codigos == valores[np.argmax(contagens)]].mean(axis=0)


def mascara_vazia(dados: bytes) -> bytes:
    """Máscara que mantém tudo: ponto de partida para quem só quer usar o pincel."""
    with Image.open(io.BytesIO(dados)) as aberta:
        tamanho = ImageOps.exif_transpose(aberta).size
    return _png(Image.new("L", tamanho, 255))


# --------------------------------------------------------------------------
# Pincel
# --------------------------------------------------------------------------


def aplicar_pinceladas(mascara: bytes, tracos: bytes | None) -> bytes:
    """Aplica o desenho do pincel sobre a máscara.

    `tracos` é um PNG com fundo transparente, de qualquer tamanho (é esticado
    para o da máscara): onde o vermelho domina, apaga; onde o verde domina,
    restaura. Traços sobrepostos valem pelo último, porque o canvas já entrega
    as cores misturadas nessa ordem.
    """
    if not tracos:
        return mascara
    with Image.open(io.BytesIO(mascara)) as aberta:
        base = aberta.convert("L")
    with Image.open(io.BytesIO(tracos)) as aberta:
        desenho = np.asarray(aberta.convert("RGBA"), dtype=np.int16)

    pintado = desenho[..., 3] > 10
    if not pintado.any():
        return mascara
    vermelho, verde = desenho[..., 0], desenho[..., 1]
    apagar = pintado & (vermelho > verde)
    restaurar = pintado & (verde >= vermelho)

    def ampliar(selecao: np.ndarray) -> np.ndarray:
        # Bilinear + corte em 50%: borda lisa em vez de escadinha ao ampliar.
        camada = Image.fromarray(selecao.astype(np.uint8) * 255, "L")
        return np.asarray(camada.resize(base.size, Image.BILINEAR)) >= 128

    resultado = np.asarray(base).copy()
    resultado[ampliar(apagar)] = 0
    resultado[ampliar(restaurar)] = 255
    return _png(Image.fromarray(resultado, "L"))


# --------------------------------------------------------------------------
# Montagem
# --------------------------------------------------------------------------


def _ajustar_borda(mascara: Image.Image, encolher: int, suavizar: float) -> Image.Image:
    if encolher > 0:
        # MinFilter precisa de tamanho ímpar: 1 px de cada lado = janela 3.
        mascara = mascara.filter(ImageFilter.MinFilter(2 * int(encolher) + 1))
    if suavizar > 0:
        # Só para dentro: espalhar para fora traria de volta a cor do fundo
        # antigo, que é o que estava ali, e o contorno ganharia um halo.
        mascara = ImageChops.darker(mascara, mascara.filter(ImageFilter.GaussianBlur(float(suavizar))))
    return mascara


def _descontaminar(imagem: Image.Image, alfa: Image.Image, cor_fundo: str) -> Image.Image:
    """Tira o "halo" da cor antiga nas bordas semitransparentes.

    Na borda de um logo sobre branco, o pixel é uma mistura: C = a·F + (1-a)·B.
    Sabendo o fundo B e o alfa a, dá para recuperar a cor F do desenho. Sem
    isso, o logo colocado sobre fundo escuro fica com um contorno claro.
    """
    a = np.asarray(alfa)
    linhas, colunas = np.nonzero((a > 5) & (a < 250))  # só o contorno: pouca memória
    if linhas.size == 0:
        return imagem
    rgb = np.array(imagem.convert("RGB"))
    peso = a[linhas, colunas].astype(np.float32)[:, None] / 255
    fundo = np.array(ImageColor.getrgb(cor_fundo)[:3], np.float32)
    misturado = rgb[linhas, colunas].astype(np.float32)
    rgb[linhas, colunas] = np.clip((misturado - (1 - peso) * fundo) / peso, 0, 255).round()
    return Image.fromarray(rgb, "RGB")


def remover_fundo(
    dados: bytes,
    mascara: bytes,
    *,
    fundo: str = "transparente",
    cor: str = "#FFFFFF",
    formato: str = "PNG",
    recortar: bool = False,
    margem: int = 0,
    encolher: int = 0,
    suavizar: float = 0,
    cor_removida: str | None = None,
    qualidade: int = 92,
) -> tuple[bytes, str, tuple[int, int]]:
    """Monta a imagem final. Devolve (conteúdo, extensão, (largura, altura)).

    fundo      - "transparente" ou "cor" (preenche com `cor`, que pode ser
                 qualquer '#RRGGBB')
    formato    - PNG, WEBP ou JPEG. JPEG não tem transparência: só com fundo "cor".
    recortar   - corta o espaço vazio em volta do que sobrou, mais `margem` px
    encolher   - come N px da borda do recorte (tira o resto de fundo que gruda)
    suavizar   - desfoque da borda, em px
    cor_removida - a cor de fundo apagada, quando se sabe (método por cor):
                 limpa o halo dessa cor nas bordas semitransparentes
    """
    if fundo not in FUNDOS_SAIDA:
        raise ValueError(f"Fundo desconhecido: {fundo}.")
    if formato not in FORMATOS_SAIDA:
        raise ValueError(f"Formato de saída desconhecido: {formato}.")
    if formato == "JPEG" and fundo == "transparente":
        raise ValueError("JPEG não guarda transparência. Use PNG ou WEBP, ou escolha uma cor de fundo.")

    imagem = _abrir(dados)
    bruta = _ler_mascara(mascara, imagem.size)
    rgb = imagem.convert("RGB")
    if cor_removida:
        # Com a máscara crua: depois de suavizar, o alfa da borda deixa de
        # medir a mistura com o fundo e a conta escureceria o contorno.
        rgb = _descontaminar(rgb, bruta, cor_removida)
    alfa = _ajustar_borda(bruta, int(encolher), float(suavizar))
    if imagem.mode == "RGBA":  # a imagem já tinha partes transparentes: elas continuam
        alfa = Image.fromarray(
            np.minimum(np.asarray(alfa), np.asarray(imagem.getchannel("A"))), "L"
        )

    caixa = alfa.point(lambda v: 255 if v > 8 else 0).getbbox()
    if caixa is None:
        raise ValueError("A imagem ficou vazia: tudo foi apagado. Restaure alguma parte com o pincel.")

    recorte = rgb.convert("RGBA")
    recorte.putalpha(alfa)

    if recortar:
        m = max(0, int(margem))
        caixa = (
            max(0, caixa[0] - m),
            max(0, caixa[1] - m),
            min(recorte.width, caixa[2] + m),
            min(recorte.height, caixa[3] + m),
        )
        recorte = recorte.crop(caixa)

    if fundo == "cor":
        base = Image.new("RGBA", recorte.size, (*ImageColor.getrgb(cor)[:3], 255))
        base.alpha_composite(recorte)
        final = base.convert("RGB")
    else:
        final = recorte

    buffer = io.BytesIO()
    qualidade = max(1, min(int(qualidade), 100))
    if formato == "JPEG":
        final.save(buffer, "JPEG", quality=qualidade, optimize=True, progressive=True)
    elif formato == "WEBP":
        final.save(buffer, "WEBP", quality=qualidade, method=4)
    else:
        final.save(buffer, "PNG", optimize=True)
    return buffer.getvalue(), _EXTENSOES[formato], final.size


# --------------------------------------------------------------------------
# Prévias (para a tela; em tamanho reduzido)
# --------------------------------------------------------------------------


def xadrez(tamanho: tuple[int, int], casa: int = 12) -> Image.Image:
    """O quadriculado cinza que os editores usam para mostrar transparência."""
    largura, altura = tamanho
    y, x = np.mgrid[0:altura, 0:largura]
    claro = ((x // casa + y // casa) % 2 == 0)
    tons = np.where(claro, 255, 214).astype(np.uint8)
    return Image.fromarray(np.dstack([tons, tons, tons]), "RGB")


def reduzir(dados: bytes, lado: int = 900) -> tuple[bytes, float]:
    """Cópia em PNG com o lado maior limitado, para prévias rápidas.

    Devolve (PNG, fator), onde fator = tamanho reduzido / original. Já sai
    girada pelo EXIF e mantém a transparência que a imagem tiver.
    """
    imagem = _abrir(dados)
    largura = imagem.width
    imagem.thumbnail((lado, lado))
    return _png(imagem), imagem.width / largura


def previa_fantasma(
    dados: bytes, mascara: bytes, caixa: tuple[int, int] = (720, 720)
) -> tuple[bytes, tuple[int, int]]:
    """Imagem para pintar por cima: o que vai sumir aparece apagadinho sobre o xadrez.

    Assim dá para ver tanto o que sobrou (e apagar mais) quanto o que foi
    removido (e restaurar). A imagem é ajustada para caber em `caixa`,
    ampliando se for pequena (logo de 200 px fica difícil de pintar).
    Devolve (PNG, tamanho da prévia).
    """
    imagem = ImageOps.contain(_abrir(dados), caixa, method=Image.LANCZOS)
    alfa = np.asarray(_ler_mascara(mascara, imagem.size), dtype=np.float32) / 255
    if imagem.mode == "RGBA":
        alfa = alfa * np.asarray(imagem.getchannel("A"), dtype=np.float32) / 255
    visivel = 0.28 + 0.72 * alfa  # o removido ainda aparece, a 28%
    fundo = np.asarray(xadrez(imagem.size), dtype=np.float32)
    cor = np.asarray(imagem.convert("RGB"), dtype=np.float32)
    mistura = cor * visivel[..., None] + fundo * (1 - visivel[..., None])
    return _png(Image.fromarray(mistura.round().astype(np.uint8), "RGB")), imagem.size


def previa_resultado(resultado: bytes, lado: int = 720) -> bytes:
    """O arquivo final em miniatura, com o xadrez atrás se for transparente."""
    with Image.open(io.BytesIO(resultado)) as aberta:
        imagem = aberta.convert("RGBA")
    imagem.thumbnail((lado, lado))
    base = xadrez(imagem.size).convert("RGBA")
    base.alpha_composite(imagem)
    return _png(base.convert("RGB"))
