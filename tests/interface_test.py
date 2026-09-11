"""Testa as telas de ponta a ponta: envia arquivo, clica, confere o download.

Roda o app de verdade pelo AppTest do Streamlit - sem navegador.
Use:  python tests/interface_test.py
"""

from __future__ import annotations

import io
import os
import pickle
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image
from streamlit.testing.v1 import AppTest

from smoke import pdf_exemplo

HARNESS = str(Path(__file__).with_name("harness.py"))
FALHAS: list[str] = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(f"  [{'ok  ' if condicao else 'FALHA'}] {nome}{(' - ' + detalhe) if detalhe else ''}")
    if not condicao:
        FALHAS.append(nome)


DEPOSITO = Path(tempfile.gettempdir()) / "harness_pdf_app.pickle"


def rodar(tela: str, arquivos: dict[str, list[tuple[str, bytes]]]) -> AppTest:
    DEPOSITO.write_bytes(pickle.dumps(arquivos))
    os.environ["HARNESS_TELA"] = tela
    os.environ["HARNESS_ARQUIVOS"] = str(DEPOSITO)
    app = AppTest.from_file(HARNESS, default_timeout=180)
    app.run()
    return app


def sem_excecao(app: AppTest, nome: str) -> bool:
    if app.exception:
        checar(nome, False, str(app.exception[0].value)[:160])
        return False
    return True


def erros(app: AppTest) -> str:
    return " | ".join(e.value for e in app.error)


def downloads(app: AppTest) -> list:
    """Botões de download presentes na tela."""
    return list(app.get("download_button"))


def resultado(app: AppTest, chave: str) -> list[tuple[str, bytes]]:
    """Arquivos gerados, lidos da sessão.

    O proto do download_button não carrega os bytes (o Streamlit serve o
    arquivo por uma URL separada), então conferimos a fonte: o que a tela
    guardou em `st.session_state`.
    """
    # O proxy de sessão do AppTest não implementa .get(), só indexação.
    nome = f"resultado_{chave}"
    if nome not in app.session_state:
        return []
    return app.session_state[nome]["arquivos"]


def clicar(app: AppTest, rotulo_contem: str) -> AppTest:
    for botao in app.button:
        if rotulo_contem.lower() in botao.label.lower():
            return botao.click().run()
    raise AssertionError(f"botão {rotulo_contem!r} não encontrado: "
                         f"{[b.label for b in app.button]}")


def imagem_png(cor=(30, 120, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (600, 400), cor).save(buffer, "PNG")
    return buffer.getvalue()


def main() -> int:
    base = pdf_exemplo()
    outro = pdf_exemplo(paginas=3)
    um = {"principal": [("manual.pdf", base)]}

    print("Telas com um PDF de entrada")

    app = rodar("tela_informacoes", um)
    if sem_excecao(app, "informações abre"):
        checar("informações abre", True)
        checar("informações mostra métricas", len(app.metric) >= 3,
               f"{len(app.metric)} métricas")

    app = rodar("tela_extrair", um)
    if sem_excecao(app, "extrair abre"):
        app.text_input(key="intervalo_extrair").set_value("2,4-6").run()
        app = clicar(app, "Gerar PDF")
        checar("extrair gera download", len(downloads(app)) == 1, erros(app))
        resultado_extrair = resultado(app, "extrair")
        if resultado_extrair:
            saida = resultado_extrair[0][1]
            import pdf_tools as pt
            checar("extrair devolve 4 páginas", pt.contar_paginas(saida) == 4)
            checar("nome do arquivo faz sentido",
                   resultado_extrair[0][0] == "manual-paginas.pdf",
                   resultado_extrair[0][0])

    app = rodar("tela_dividir", um)
    if sem_excecao(app, "dividir abre"):
        app = clicar(app, "Dividir")
        checar("dividir gera zip", len(downloads(app)) >= 1, erros(app))

    app = rodar("tela_comprimir", um)
    if sem_excecao(app, "comprimir abre"):
        checar("comprimir detecta imagens",
               any("imagem" in i.value.lower() for i in app.info), erros(app))
        app = clicar(app, "Comprimir")
        checar("comprimir gera download", len(downloads(app)) == 1, erros(app))
        if downloads(app):
            import pdf_tools as pt
            antes, depois = len(base), len(resultado(app, "comprimir")[0][1])
            checar("comprimir encolhe", depois < antes,
                   f"{pt.tamanho_legivel(antes)} -> {pt.tamanho_legivel(depois)}")
            checar("mostra resumo do ganho",
                   any("menor" in s.value for s in app.success),
                   " ".join(s.value for s in app.success)[:90])

    app = rodar("tela_pdf_para_imagens", um)
    if sem_excecao(app, "pdf→imagens abre"):
        app.text_input(key="intervalo_pdf2img").set_value("1-2").run()
        app = clicar(app, "Converter")
        checar("pdf→imagens gera zip", len(downloads(app)) >= 1, erros(app))

    app = rodar("tela_texto", um)
    if sem_excecao(app, "texto abre"):
        app = clicar(app, "Extrair")
        checar("texto gera .txt", len(downloads(app)) >= 1, erros(app))
        if downloads(app):
            conteudo = resultado(app, "texto")[0][1].decode("utf-8")
            checar("texto tem conteúdo", "Pagina 1" in conteudo, conteudo[:40])

    app = rodar("tela_organizar", um)
    if sem_excecao(app, "organizar abre"):
        checar("organizar mostra miniaturas", len(app.get("image")) >= 1,
               f"{len(app.get('image'))} imagens")
        app = clicar(app, "Girar tudo 90")
        app = clicar(app, "Gerar PDF organizado")
        checar("organizar gera download", len(downloads(app)) == 1, erros(app))

    app = rodar("tela_numerar", um)
    if sem_excecao(app, "numerar abre"):
        app = clicar(app, "Numerar")
        checar("numerar gera download", len(downloads(app)) == 1, erros(app))
        if downloads(app):
            import pdf_tools as pt
            conteudo, _ = pt.extrair_texto(resultado(app, "numerar")[0][1],
                                           intervalo="3", com_cabecalho=False)
            checar("número aparece na página", "3" in conteudo.split()[-3:][-1:][0]
                   if conteudo.split() else False, conteudo.replace("\n", " ")[-40:])

    app = rodar("tela_proteger", um)
    if sem_excecao(app, "proteger abre"):
        checar("proteger começa desabilitado", len(downloads(app)) == 0)
        app.text_input(key="prot_abertura").set_value("abc123").run()
        app.text_input(key="prot_confere").set_value("abc123").run()
        app = clicar(app, "Proteger")
        checar("proteger gera download", len(downloads(app)) == 1, erros(app))
        if downloads(app):
            import pdf_tools as pt
            checar("resultado pede senha",
                   pt.precisa_de_senha(resultado(app, "proteger")[0][1]))

    print("\nTela com PDF já protegido")
    import pdf_tools as pt
    trancado = pt.proteger(base, senha_abertura="segredo")
    app = rodar("tela_desbloquear", {"principal": [("trancado.pdf", trancado)]})
    if sem_excecao(app, "desbloquear pede senha"):
        campos = [t for t in app.text_input if "senha" in t.label.lower()]
        checar("desbloquear pede senha", len(campos) == 1,
               f"{[t.label for t in app.text_input]}")
        app = app.text_input(key="senha_desbloquear").set_value("segredo").run()
        checar("abre com a senha certa", not app.exception and len(app.button) >= 1,
               erros(app))
        app = clicar(app, "Desbloquear")
        checar("desbloquear gera download", len(downloads(app)) == 1, erros(app))
        if downloads(app):
            checar("resultado abre sem senha",
                   not pt.precisa_de_senha(resultado(app, "desbloquear")[0][1]))

    app = rodar("tela_desbloquear", um)
    if sem_excecao(app, "avisa quando já está livre"):
        checar("avisa quando já está livre",
               any("livre" in s.value for s in app.success),
               " ".join(s.value for s in app.success)[:80])

    print("\nTelas com vários arquivos")

    app = rodar("tela_juntar", {"todos": [("a.pdf", base), ("b.pdf", outro)]})
    if sem_excecao(app, "juntar abre"):
        app = clicar(app, "Juntar")
        checar("juntar gera download", len(downloads(app)) == 1, erros(app))
        if downloads(app):
            checar("juntar soma as páginas",
                   pt.contar_paginas(resultado(app, "juntar")[0][1]) == 9,
                   str(pt.contar_paginas(resultado(app, "juntar")[0][1])))
        app = clicar(app, "Inverter")
        checar("inverter limpa o resultado antigo", len(downloads(app)) == 0)

    app = rodar("tela_imagens_para_pdf",
                {"imagens": [("2.png", imagem_png()), ("1.png", imagem_png((200, 60, 60)))]})
    if sem_excecao(app, "imagens→pdf abre"):
        app = clicar(app, "Gerar PDF")
        checar("imagens→pdf gera download", len(downloads(app)) == 1, erros(app))
        if downloads(app):
            checar("uma página por imagem",
                   pt.contar_paginas(resultado(app, "img2pdf")[0][1]) == 2)

    print("\nMarca d'água (dois uploaders na mesma tela)")
    app = rodar("tela_marca_dagua", {"pdf": [("manual.pdf", base)],
                                     "logo": [("logo.png", imagem_png())]})
    if sem_excecao(app, "marca d'água abre"):
        checar("marca d'água gera prévia", len(app.get("image")) >= 1,
               f"{len(app.get('image'))} imagens")
        app = clicar(app, "Aplicar marca d'água")
        checar("marca d'água gera download", len(downloads(app)) >= 1, erros(app))
        if downloads(app):
            conteudo, _ = pt.extrair_texto(resultado(app, "marca_texto")[0][1],
                                           intervalo="1", com_cabecalho=False)
            checar("texto da marca está no PDF", "CONFIDENCIAL" in conteudo)

    print("\nRedimensionar imagens (lote)")
    em_pe = io.BytesIO()
    Image.new("RGB", (300, 500), (20, 160, 90)).save(em_pe, "JPEG")
    lote = {"imagens": [("azul.png", imagem_png()), ("vermelha.png", imagem_png((200, 60, 60))),
                        ("em-pe.jpg", em_pe.getvalue())]}

    app = rodar("tela_redimensionar", lote)
    if sem_excecao(app, "redimensionar abre"):
        checar("prévia antes/depois", len(app.get("image")) >= 2,
               f"{len(app.get('image'))} imagens")
        app.number_input(key="redim_largura").set_value(320).run()
        app.number_input(key="redim_altura").set_value(240).run()
        checar("antecipa o tamanho final",
               any("320 × 240" in i.value for i in app.info),
               " | ".join(i.value for i in app.info)[:80])
        app = clicar(app, "Redimensionar")
        prontos = resultado(app, "redim")
        checar("devolve as três", len(prontos) == 3 and len(downloads(app)) >= 1, erros(app))
        tamanhos = [Image.open(io.BytesIO(d)).size for _, d in prontos]
        checar("todas em 320 × 240", tamanhos == [(320, 240)] * 3, str(tamanhos))
        checar("nome traz o tamanho", all("-320x240." in n for n, _ in prontos),
               str([n for n, _ in prontos]))
        app.number_input(key="redim_largura").set_value(100).run()
        checar("mudar o tamanho esconde o resultado antigo", len(downloads(app)) == 0)

    app = rodar("tela_redimensionar", lote)
    if sem_excecao(app, "modo lado maior"):
        app.radio(key="redim_modo").set_value("Lado maior").run()
        app.number_input(key="redim_lado").set_value(250).run()
        app = clicar(app, "Redimensionar")
        tamanhos = [Image.open(io.BytesIO(d)).size for _, d in resultado(app, "redim")]
        checar("lado maior respeita a proporção de cada uma",
               tamanhos == [(250, 167), (250, 167), (150, 250)], str(tamanhos))

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s): {', '.join(FALHAS)}")
        return 1
    print("Todas as telas passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
