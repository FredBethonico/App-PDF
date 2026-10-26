"""Teste de fumaça: exercita todas as ferramentas com um PDF gerado na hora.

Rode com:  python tests/smoke.py
Não precisa de pytest nem de arquivo de exemplo.
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import pdf_tools as pt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FALHAS: list[str] = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    marca = "ok  " if condicao else "FALHA"
    print(f"  [{marca}] {nome}{(' - ' + detalhe) if detalhe else ''}")
    if not condicao:
        FALHAS.append(nome)


def foto(largura: int = 900, altura: int = 700) -> bytes:
    """Ruído colorido: não comprime bem, então dá para medir a compressão."""
    random.seed(7)
    imagem = Image.new("RGB", (largura, altura))
    imagem.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(largura * altura)
        ]
    )
    buffer = io.BytesIO()
    imagem.save(buffer, "PNG")
    return buffer.getvalue()


def pdf_exemplo(paginas: int = 6, com_imagem: bool = True) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    imagem = ImageReader(io.BytesIO(foto())) if com_imagem else None
    for numero in range(1, paginas + 1):
        if numero == 3:
            c.setPageSize(landscape(A4))  # uma página fora do padrão, de propósito
        else:
            c.setPageSize(A4)
        c.setFont("Helvetica-Bold", 28)
        c.drawString(60, 700, f"Pagina {numero}")
        c.setFont("Helvetica", 12)
        c.drawString(60, 660, f"Conteudo de teste da pagina {numero} - acentuacao: ção")
        if imagem is not None:
            c.drawImage(imagem, 60, 300, width=400, height=300)
        c.showPage()
    c.save()
    return buffer.getvalue()


def video_exemplo(segundos: float = 3, com_audio: bool = True, taxa: int = 44100) -> bytes:
    """MP4 de verdade, feito na hora: tela preta e um tom de 440 Hz em estéreo."""
    import math

    import av
    import numpy as np

    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp4") as saida:
        video = saida.add_stream("mpeg4", rate=10)
        video.width, video.height, video.pix_fmt = 64, 48, "yuv420p"
        audio = None
        if com_audio:
            audio = saida.add_stream("aac", rate=taxa)
            audio.layout = "stereo"
        for indice in range(int(segundos * 10)):
            quadro = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), np.uint8), format="rgb24")
            quadro.pts = indice
            for pacote in video.encode(quadro):
                saida.mux(pacote)
        amostra = 0
        while audio is not None and amostra < taxa * segundos:
            tempo = (np.arange(1024) + amostra) / taxa
            onda = (0.3 * np.sin(2 * math.pi * 440 * tempo)).astype(np.float32)
            quadro = av.AudioFrame.from_ndarray(np.stack([onda, onda]), format="fltp", layout="stereo")
            quadro.sample_rate, quadro.pts = taxa, amostra
            for pacote in audio.encode(quadro):
                saida.mux(pacote)
            amostra += 1024
        for fluxo in (video, audio):
            for pacote in fluxo.encode(None) if fluxo else ():
                saida.mux(pacote)
    return buffer.getvalue()


def secao(titulo: str) -> None:
    print(f"\n{titulo}")


def main() -> int:
    base = pdf_exemplo()
    print(f"PDF de teste: {pt.tamanho_legivel(len(base))}, 6 páginas")

    secao("Informações")
    info = pt.inspecionar(base)
    checar("conta páginas", info.paginas == 6, f"{info.paginas}")
    checar("detecta A4", "A4" in info.descricao_pagina(0), info.descricao_pagina(0))
    checar("detecta paisagem", "paisagem" in info.descricao_pagina(2), info.descricao_pagina(2))
    checar("tamanhos diferentes", not info.paginas_iguais)
    checar("não criptografado", not info.criptografado)

    secao("Proteger e desbloquear")
    trancado = pt.proteger(base, senha_abertura="segredo", permitir_impressao=False)
    checar("exige senha", pt.precisa_de_senha(trancado))
    try:
        pt.inspecionar(trancado)
        checar("erro sem senha", False)
    except pt.PdfProtegido:
        checar("erro sem senha", True)
    info_trancado = pt.inspecionar(trancado, "segredo")
    checar("abre com senha", info_trancado.paginas == 6)
    checar("bloqueia impressão", info_trancado.permissoes.get("Imprimir") is False)
    livre = pt.desbloquear(trancado, "segredo")
    checar("desbloqueia", not pt.inspecionar(livre).criptografado)

    so_dono = pt.proteger(base, senha_dono="dono", permitir_copia=False)
    checar("senha só de dono abre sem senha", not pt.precisa_de_senha(so_dono))
    checar("desbloqueia sem senha", not pt.inspecionar(pt.desbloquear(so_dono)).criptografado)

    secao("Páginas")
    recorte = pt.extrair(base, "2,4-6")
    checar("extrai 4 páginas", pt.inspecionar(recorte).paginas == 4)
    checar("recorte é menor", len(recorte) < len(base),
           f"{pt.tamanho_legivel(len(base))} -> {pt.tamanho_legivel(len(recorte))}")
    invertido = pt.extrair(base, "6-1")
    checar("extrai invertido", pt.inspecionar(invertido).paginas == 6)
    checar("remove páginas", pt.inspecionar(pt.remover(base, "1-2")).paginas == 4)

    blocos = pt.dividir_em_blocos(base, 2, "manual.pdf")
    checar("divide em blocos", len(blocos) == 3, f"{[n for n, _ in blocos]}")
    checar("nomes com faixa", "p1-2" in blocos[0][0], blocos[0][0])
    partes = pt.dividir_em_partes(base, 4, "manual.pdf")
    checar("divide em partes 2+2+1+1", len(partes) == 4 and
           [pt.inspecionar(d).paginas for _, d in partes] == [2, 2, 1, 1], f"{[pt.inspecionar(d).paginas for _, d in partes]}")
    faixas = pt.dividir_por_intervalos(base, ["1-2", "5-6"], "manual.pdf")
    checar("divide por intervalos", len(faixas) == 2)

    unido = pt.juntar([("capitulo-um.pdf", base), ("capitulo-dois.pdf", recorte)])
    checar("junta PDFs", pt.inspecionar(unido).paginas == 10)

    reorganizado = pt.organizar(base, ordem=[5, 0, 1], rotacoes={0: 90})
    checar("reorganiza", pt.inspecionar(reorganizado).paginas == 3)
    girado = pt.girar_tudo(base, 90)
    antes = pt.inspecionar(base).tamanhos_pagina[0]
    depois = pt.inspecionar(girado).tamanhos_pagina[0]
    checar("girar troca orientação", antes[0] == depois[1] and antes[1] == depois[0],
           f"{antes} -> {depois}")

    secao("Compressão")
    estrutura = pt.comprimir_estrutura(base)
    checar("estrutura roda", pt.inspecionar(estrutura).paginas == 6,
           f"{pt.variacao_percentual(len(base), len(estrutura)):.1f}%")
    reduzido, trocadas = pt.comprimir_imagens(base, qualidade=60, lado_maximo=800)
    checar("recomprime imagens", trocadas > 0, f"{trocadas} imagem(ns)")
    checar("arquivo encolheu", len(reduzido) < len(base) * 0.6,
           f"{pt.tamanho_legivel(len(base))} -> {pt.tamanho_legivel(len(reduzido))} "
           f"({pt.variacao_percentual(len(base), len(reduzido)):.1f}%)")
    checar("páginas preservadas", pt.inspecionar(reduzido).paginas == 6)
    texto_apos, _ = pt.extrair_texto(reduzido, intervalo="1", com_cabecalho=False)
    checar("texto sobrevive à compressão", "Pagina 1" in texto_apos)

    raster = pt.rasterizar(base, dpi=100, qualidade=60)
    info_raster = pt.inspecionar(raster)
    checar("rasteriza", info_raster.paginas == 6)
    a4_pt = (595.3, 841.9)
    largura, altura = info_raster.tamanhos_pagina[0]
    checar("mantém tamanho da página", abs(largura - a4_pt[0]) < 3 and abs(altura - a4_pt[1]) < 3,
           f"{largura} x {altura}")
    l3, a3 = info_raster.tamanhos_pagina[2]
    checar("mantém página paisagem", l3 > a3, f"{l3} x {a3}")
    diag = pt.diagnostico(base)
    checar("diagnóstico acha imagens", diag["imagens"] >= 1 and diag["fracao_imagem"] > 0.5,
           f'{diag["imagens"]} obj, {diag["fracao_imagem"]:.0%} do arquivo')

    secao("Imagens")
    saidas = pt.pdf_para_imagens(base, dpi=72, formato="JPEG", intervalo="1-2", nome="manual.pdf")
    checar("PDF vira imagens", len(saidas) == 2, f"{[n for n, _ in saidas]}")
    with Image.open(io.BytesIO(saidas[0][1])) as img:
        checar("resolução plausível", 580 < img.width < 610, f"{img.width}x{img.height}")

    png_alfa = io.BytesIO()
    Image.new("RGBA", (400, 300), (255, 0, 0, 128)).save(png_alfa, "PNG")
    montado = pt.imagens_para_pdf(
        [("a.jpg", saidas[0][1]), ("b.png", png_alfa.getvalue())]
    )
    checar("imagens viram PDF (com alfa)", pt.inspecionar(montado).paginas == 2)
    em_a4 = pt.imagens_para_pdf(
        [("a.jpg", saidas[0][1])], tamanho_pagina="A4 retrato", margem_mm=15
    )
    largura, altura = pt.inspecionar(em_a4).tamanhos_pagina[0]
    checar("respeita A4", abs(largura - 595.3) < 2 and abs(altura - 841.9) < 2,
           f"{largura} x {altura}")

    secao("Marcas")
    marcado = pt.marca_dagua_texto(base, "CONFIDENCIAL", mosaico=True, opacidade=0.12)
    checar("marca d'água em mosaico", pt.inspecionar(marcado).paginas == 6)
    texto_marcado, _ = pt.extrair_texto(marcado, intervalo="1", com_cabecalho=False)
    checar("original preservado sob a marca", "Pagina 1" in texto_marcado)
    checar("marca aparece no texto", "CONFIDENCIAL" in texto_marcado)

    parcial = pt.marca_dagua_texto(base, "RASCUNHO", intervalo="1,3", angulo=30)
    t1, _ = pt.extrair_texto(parcial, intervalo="1", com_cabecalho=False)
    t2, _ = pt.extrair_texto(parcial, intervalo="2", com_cabecalho=False)
    checar("marca só nas páginas pedidas", "RASCUNHO" in t1 and "RASCUNHO" not in t2)

    logo = io.BytesIO()
    Image.new("RGBA", (200, 80), (0, 90, 200, 200)).save(logo, "PNG")
    com_logo = pt.marca_dagua_imagem(base, logo.getvalue(), largura_relativa=0.3,
                                     posicao="Rodapé direita")
    checar("marca d'água de imagem", pt.inspecionar(com_logo).paginas == 6)

    numerado = pt.numerar_paginas(base, formato="Página {n} de {total}",
                                  comecar_na_pagina=2, primeiro_numero=1)
    t1, _ = pt.extrair_texto(numerado, intervalo="1", com_cabecalho=False)
    t2, _ = pt.extrair_texto(numerado, intervalo="2", com_cabecalho=False)
    t6, _ = pt.extrair_texto(numerado, intervalo="6", com_cabecalho=False)
    checar("capa fica sem número", "Página 1 de 5" not in t1)
    checar("numeração começa na 2", "Página 1 de 5" in t2, t2.replace(chr(10), " | ")[:60])
    checar("última numerada", "Página 5 de 5" in t6)
    alternado = pt.numerar_paginas(base, posicao="Alternado (livro)")
    checar("numeração alternada roda", pt.inspecionar(alternado).paginas == 6)

    secao("Texto")
    texto, vazias = pt.extrair_texto(base)
    checar("extrai texto", "Pagina 4" in texto)
    checar("mantém acentos", "ção" in texto)
    checar("nenhuma página vazia", vazias == 0, f"{vazias}")
    _, vazias_raster = pt.extrair_texto(raster)
    checar("detecta PDF sem camada de texto", vazias_raster == 6, f"{vazias_raster}")

    secao("Redimensionar imagens")

    def imagem_bytes(img, formato, **kw):
        buffer = io.BytesIO()
        img.save(buffer, formato, **kw)
        return buffer.getvalue()

    def medir(dados):
        with Image.open(io.BytesIO(dados)) as img:
            return img.size, img.mode

    deitada_alfa = imagem_bytes(Image.new("RGBA", (1200, 800), (255, 0, 0, 128)), "PNG")
    em_pe = imagem_bytes(Image.new("RGB", (800, 1200), (0, 128, 255)), "JPEG")
    exif = Image.Exif()
    exif[0x0112] = 6  # celular: gravada deitada, com ordem de girar 90°
    celular = imagem_bytes(Image.new("RGB", (1200, 800), "green"), "JPEG", exif=exif)

    feitas, falhas = pt.redimensionar_lote(
        [("a.png", deitada_alfa), ("b.jpg", em_pe), ("c.jpg", celular)],
        modo="exato", largura=500, altura=500,
    )
    checar("lote no tamanho exato", [medir(d)[0] for _, d in feitas] == [(500, 500)] * 3)
    checar("nomes com o tamanho", [n for n, _ in feitas] == ["a-500x500.png", "b-500x500.jpg",
                                                          "c-500x500.jpg"], str([n for n, _ in feitas]))
    checar("PNG continua com transparência", medir(feitas[0][1])[1] == "RGBA")

    _, _, tamanho = pt.redimensionar_imagem(deitada_alfa, modo="largura", largura=600)
    checar("só a largura mantém proporção", tamanho == (600, 400), str(tamanho))
    _, _, tamanho = pt.redimensionar_imagem(em_pe, modo="lado_maior", lado=600)
    checar("lado maior em foto em pé", tamanho == (400, 600), str(tamanho))
    _, _, tamanho = pt.redimensionar_imagem(em_pe, modo="lado_maior", lado=5000, nao_ampliar=True)
    checar("não amplia quando pedido", tamanho == (800, 1200), str(tamanho))
    checar("lê o giro do celular", pt.dimensoes_imagem(celular) == (800, 1200))
    _, _, tamanho = pt.redimensionar_imagem(celular, modo="largura", largura=400)
    checar("foto de celular sai em pé", tamanho == (400, 600), str(tamanho))

    com_fundo, _, _ = pt.redimensionar_imagem(deitada_alfa, modo="exato", largura=400,
                                               altura=400, encaixe="fundo", transparente=True)
    with Image.open(io.BytesIO(com_fundo)) as img:
        checar("faixa de fundo transparente", img.getpixel((200, 3))[3] == 0)
    como_jpeg, extensao, _ = pt.redimensionar_imagem(deitada_alfa, modo="largura", largura=300,
                                                      formato="JPEG")
    checar("PNG com alfa vira JPEG", extensao == ".jpg" and medir(como_jpeg)[1] == "RGB")

    feitas, falhas = pt.redimensionar_lote(
        [("boa.png", deitada_alfa), ("quebrada.png", b"lixo")], modo="largura", largura=100
    )
    checar("arquivo quebrado não derruba o lote", len(feitas) == 1 and len(falhas) == 1,
           falhas[0][:40] if falhas else "")

    secao("MP4 para MP3")
    import av

    def ler_mp3(dados):
        with av.open(io.BytesIO(dados)) as c:
            faixa = c.streams.audio[0]
            return c.format.name, faixa.codec_context.channels, c.duration / av.time_base, c.bit_rate

    video = video_exemplo(segundos=4)
    info = pt.info_audio(video)
    checar("lê duração do vídeo", abs(info.duracao - 4) < 0.2, f"{info.duracao:.2f}s")
    checar("lê canais e taxa", (info.canais, info.taxa) == (2, 44100), f"{info.canais}, {info.taxa}")
    formato, canais, duracao, _ = ler_mp3(pt.converter_para_mp3(video))
    checar("sai MP3 estéreo", formato == "mp3" and canais == 2, f"{formato}, {canais}")
    checar("mantém a duração", abs(duracao - 4) < 0.2, f"{duracao:.2f}s")
    _, canais, _, _ = ler_mp3(pt.converter_para_mp3(video, mono=True))
    checar("mono mistura os canais", canais == 1)
    leve = pt.converter_para_mp3(video, bitrate=128)
    pesado = pt.converter_para_mp3(video, bitrate=320)
    checar("320 kbps maior que 128", len(pesado) > len(leve) * 2,
           f"{pt.tamanho_legivel(len(leve))} x {pt.tamanho_legivel(len(pesado))}")
    _, _, duracao, _ = ler_mp3(pt.converter_para_mp3(video, inicio=1, fim=2.5))
    checar("corta o trecho", abs(duracao - 1.5) < 0.15, f"{duracao:.2f}s")
    _, _, duracao, _ = ler_mp3(pt.converter_para_mp3(video, inicio=3))
    checar("do meio até o fim", abs(duracao - 1) < 0.15, f"{duracao:.2f}s")
    _, _, duracao, _ = ler_mp3(pt.converter_para_mp3(video_exemplo(2, taxa=96000)))
    checar("taxa fora do MP3 é reamostrada", abs(duracao - 2) < 0.2, f"{duracao:.2f}s")
    checar("tempo 1:02:03", pt.ler_tempo("1:02:03") == 3723)
    checar("tempo com vírgula", pt.ler_tempo("1:30,5") == 90.5)
    checar("tempo em branco", pt.ler_tempo(" ") is None)
    checar("formata tempo", pt.formatar_tempo(83.4) == "1:23" and pt.formatar_tempo(3723) == "1:02:03")

    feitos, falhas = pt.converter_lote(
        [("aula.mp4", video), ("mudo.mp4", video_exemplo(1, com_audio=False)), ("lixo.mp4", b"x" * 500)]
    )
    checar("lote com nome .mp3", [n for n, _ in feitos] == ["aula.mp3"], str([n for n, _ in feitos]))
    checar("vídeo mudo e lixo ficam de fora", len(falhas) == 2
           and "faixa de som" in falhas[0] and "não consegui ler" in falhas[1], " | ".join(falhas))

    secao("Instagram (rede simulada)")
    import instagram_falso
    import pdf_tools.instagram as ig

    for link, esperado in [
        ("https://www.instagram.com/p/CARROSSEL1/?igsh=abc", "CARROSSEL1"),
        ("instagram.com/reel/REEL123456", "REEL123456"),
        ("https://www.instagram.com/reels/REEL123456/", "REEL123456"),
        ("https://m.instagram.com/fulano/p/FOTO123456/", "FOTO123456"),
        ("https://instagr.am/tv/Ab-c_12345", "Ab-c_12345"),
    ]:
        checar(f"entende {link[:38]}", pt.extrair_shortcode(link) == esperado)
    for link, trecho in [
        ("", "Cole o link"),
        ("https://youtube.com/watch?v=x", "não é do Instagram"),
        ("https://www.instagram.com/stories/fulano/123/", "Stories"),
        ("https://www.instagram.com/fulano/", "perfil"),
    ]:
        try:
            pt.extrair_shortcode(link)
            checar(f"recusa {link or 'vazio'}", False, "não levantou erro")
        except pt.ErroInstagram as erro:
            checar(f"recusa {link or 'vazio'}", trecho in str(erro), str(erro)[:60])

    checar("extensão JPEG", ig.extensao(instagram_falso.jpeg(), False) == ".jpg")
    checar("extensão WEBP num link .jpg", ig.extensao(instagram_falso.webp(), False) == ".webp")
    checar("extensão MP4", ig.extensao(instagram_falso.MP4, True) == ".mp4")

    logado = ig._novo_loader({"sessionid": "abc", "usuario": "teste"})
    checar("sessão só com sessionid carrega", logado.context.is_logged_in)
    checar("sem sessão fica anônimo", not ig._novo_loader(None).context.is_logged_in)
    try:
        ig._SemEspera(logado.context).sleep(600)
        checar("não dorme minutos no limite", False, "dormiu")
    except pt.ErroInstagram as erro:
        checar("não dorme minutos no limite", True, str(erro)[:50])

    instagram_falso.instalar()
    post = pt.ler_post("https://www.instagram.com/p/CARROSSEL1/")
    checar("carrossel com 3 itens", len(post.midias) == 3 and (post.fotos, post.videos) == (2, 1))
    feitos, falhas = pt.baixar_midias(post)
    checar("nomes do carrossel", [n for n, _ in feitos] == [
        "fulano-CARROSSEL1-01.jpg", "fulano-CARROSSEL1-02.mp4", "fulano-CARROSSEL1-03.webp"
    ], str([n for n, _ in feitos]))
    feitos, _ = pt.baixar_midias(pt.ler_post("instagram.com/reel/REEL123456"))
    checar("reel baixa o vídeo, não a capa", [n for n, _ in feitos] == ["fulano-REEL123456.mp4"],
           str([n for n, _ in feitos]))
    feitos, falhas = pt.baixar_midias(pt.ler_post("instagram.com/p/MEIOQUEBRADO"))
    checar("item quebrado não derruba o carrossel", len(feitos) == 1 and len(falhas) == 1,
           falhas[0] if falhas else "")
    for shortcode, trecho in [
        ("SUMIU12345", "não entregou"),
        ("LIMITE1234", "limitando"),
        ("LOGIN12345", "login"),
        ("MUDOU12345", "formato"),
    ]:
        try:
            pt.ler_post(f"instagram.com/p/{shortcode}")
            checar(f"erro amigável {shortcode}", False, "não levantou erro")
        except pt.ErroInstagram as erro:
            checar(f"erro amigável {shortcode}", trecho in str(erro), str(erro)[:60])

    secao("Utilidades")
    pacote = pt.zipar([("a.pdf", base), ("a.pdf", recorte)])
    import zipfile
    with zipfile.ZipFile(io.BytesIO(pacote)) as zf:
        checar("zip evita nomes repetidos", len(zf.namelist()) == 2, str(zf.namelist()))
    checar("sufixa nome", pt.sufixar("Relatório Final.pdf", "comprimido")
           == "Relatório Final-comprimido.pdf", pt.sufixar("Relatório Final.pdf", "comprimido"))
    checar("limpa nome inválido", "/" not in pt.nome_seguro("a/b:c*.pdf"))

    secao("Erros amigáveis")
    for rotulo, funcao in [
        ("PDF inválido", lambda: pt.inspecionar(b"isso nao e um pdf")),
        ("intervalo fora da faixa", lambda: pt.extrair(base, "99")),
        ("remover tudo", lambda: pt.remover(base, "1-6")),
        ("juntar só um", lambda: pt.juntar([("a.pdf", base)])),
        ("marca sem texto", lambda: pt.marca_dagua_texto(base, "   ")),
        ("formato sem {n}", lambda: pt.numerar_paginas(base, formato="fixo")),
        ("proteger sem senha", lambda: pt.proteger(base)),
        ("redimensionar sem altura",
         lambda: pt.redimensionar_lote([("a.png", b"x")], modo="exato", largura=10)),
        ("redimensionar acima do limite",
         lambda: pt.redimensionar_lote([("a.png", b"x")], modo="largura", largura=99999)),
        ("mp3 com qualidade inválida", lambda: pt.converter_lote([("a.mp4", b"x")], bitrate=100)),
        ("mp3 com fim antes do início",
         lambda: pt.converter_lote([("a.mp4", b"x")], inicio=10, fim=5)),
        ("mp3 começando depois do fim", lambda: pt.converter_para_mp3(video, inicio=60)),
        ("tempo ilegível", lambda: pt.ler_tempo("1 minuto")),
    ]:
        try:
            funcao()
            checar(rotulo, False, "não levantou erro")
        except (ValueError, pt.PdfInvalido, pt.PdfProtegido) as erro:
            checar(rotulo, True, str(erro)[:70])

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s): {', '.join(FALHAS)}")
        return 1
    print("Tudo passou.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
