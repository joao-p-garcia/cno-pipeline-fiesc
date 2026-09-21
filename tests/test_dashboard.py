"""Testes do dashboard, sem navegador.

O `AppTest` do próprio Streamlit executa o script do app num runtime de mentira e
devolve os elementos que ele produziu. É o que permite tratar o dashboard como
código testável em vez de "abre e vê se aparece" — e o que pega a classe de erro
mais comum aqui: uma coluna renomeada na camada curada que só quebraria quando
alguém clicasse na quarta seção.

Cada seção é exercitada uma a uma, sobre a camada sintética.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cno_pipeline.config import Settings
from cno_pipeline.curate import executar_curadoria
from cno_pipeline.transform import executar_staging

from .dados_sinteticos import SNAPSHOT

streamlit = pytest.importorskip(
    "streamlit", reason="Streamlit não instalado (pip install -e '.[dashboard]')"
)
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

RAIZ = Path(__file__).resolve().parents[1]
# Espelha `componentes.ORDEM` de propósito: se alguém acrescentar uma seção e
# esquecer o teste, a asserção logo abaixo falha em vez de a seção nova ficar
# sem cobertura nenhuma.
SECOES = (
    "fonte",
    "tabelas",
    "arquitetura",
    "dags",
    "nulos",
    "area",
    "geo",
    "tempo",
    "camadas",
    "conclusoes",
)


@pytest.fixture(autouse=True)
def cache_limpo():
    """Zera os caches do Streamlit entre um teste e outro.

    `st.cache_resource` guarda a conexão DuckDB por **processo**, não por
    execução: sem esta limpeza, o teste que aponta para um diretório vazio
    reaproveitaria a conexão aberta pelo teste anterior e passaria por engano.
    """
    streamlit.cache_resource.clear()
    streamlit.cache_data.clear()
    yield
    streamlit.cache_resource.clear()
    streamlit.cache_data.clear()


@pytest.fixture
def camada_curada(camada_raw: Settings, monkeypatch) -> Settings:
    """Camada curada sintética, apontada pelo mesmo `CNO_DATA_DIR` que o app lê.

    O app não recebe caminho por parâmetro de propósito: quem decide onde os
    dados moram é o `Settings` do pipeline. O teste então configura o ambiente,
    como faria qualquer implantação.
    """
    executar_staging(camada_raw, snapshot_id=SNAPSHOT)
    executar_curadoria(camada_raw, snapshot_id=SNAPSHOT)
    monkeypatch.setenv("CNO_DATA_DIR", str(camada_raw.data_dir))
    return camada_raw


def _rodar(secao: str, tmp_path):
    """Executa uma seção isolada, como o `st.navigation` faria ao abri-la."""
    script = tmp_path / f"secao_{secao}.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(RAIZ)!r})\n"
        "from app import componentes as ui\n"
        f"from app.secoes import {secao}\n"
        "ui.configurar_pagina()\n"
        f"{secao}.render()\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script), default_timeout=120)
    app.run()
    return app


def test_secoes_do_teste_espelham_a_ordem_do_app():
    """A lista acima não pode divergir de `componentes.ORDEM`.

    Sem isto, acrescentar uma seção e esquecer de listá-la aqui deixaria a seção
    nova **sem teste nenhum** — e o parametrize continuaria verde, porque ele só
    sabe o que esta lista diz.
    """
    import sys

    sys.path.insert(0, str(RAIZ))
    from app import componentes

    assert SECOES == componentes.ORDEM


@pytest.mark.parametrize("secao", SECOES)
def test_svg_nao_passa_pelo_markdown(secao, camada_curada, tmp_path):
    """Diagrama inline vai por `st.html`, nunca por `st.markdown`.

    Markdown fecha um bloco de HTML na primeira linha em branco e trata linha
    indentada em quatro espaços como bloco de código — os dois existem num SVG
    escrito de forma legível. Pelo `st.markdown(unsafe_allow_html=True)` o
    Streamlit desenhava só a primeira caixa do diagrama e despejava o resto na
    página como parágrafos soltos, um `<text>` por linha.

    O teste de renderização não pega isso: a seção desenha sem exceção nos dois
    casos. O que distingue é **onde** o fragmento sai — `st.html` não aparece em
    `app.markdown`, então um `<svg>` visto aqui significa que alguém o entregou
    pelo caminho errado.
    """
    app = _rodar(secao, tmp_path)
    culpados = [bloco.value[:80] for bloco in app.markdown if "<svg" in bloco.value]
    assert not culpados, f"{secao}: SVG entregue por st.markdown — use st.html. {culpados}"


@pytest.mark.parametrize("secao", SECOES)
def test_secao_renderiza_sem_excecao(secao, camada_curada, tmp_path):
    app = _rodar(secao, tmp_path)
    assert not app.exception, [str(e.value) for e in app.exception]
    assert app.markdown, "a seção não escreveu nada"


def test_app_inteiro_sobe(camada_curada, tmp_path):
    """A navegação em si: dez páginas, e nenhuma pode colidir de URL."""
    app = AppTest.from_file(str(RAIZ / "app" / "dashboard.py"), default_timeout=120)
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]


def test_sem_camada_curada_o_app_explica_o_que_fazer(monkeypatch, tmp_path):
    """Sem dados, o app precisa ensinar o comando — não mostrar traceback de DuckDB."""
    monkeypatch.setenv("CNO_DATA_DIR", str(tmp_path / "vazio"))
    app = AppTest.from_file(str(RAIZ / "app" / "dashboard.py"), default_timeout=120)
    app.run()
    assert not app.exception
    assert any("make pipeline" in bloco.value for bloco in app.code)


# ---------------------------------------------------------------------------
# O tema tem duas metades, e elas precisam concordar
# ---------------------------------------------------------------------------


# O caminho importa e é testado junto: o Streamlit acha config em três lugares,
# e só este é independente do diretório de trabalho. Ver o cabeçalho do arquivo.
CONFIG_TEMA = RAIZ / "app" / ".streamlit" / "config.toml"


def _config_do_tema() -> dict:
    import tomllib

    assert CONFIG_TEMA.is_file(), (
        f"{CONFIG_TEMA.relative_to(RAIZ)} não existe — se o arquivo voltar para a raiz "
        "do repositório, o tema some dentro do container e só lá"
    )
    with CONFIG_TEMA.open("rb") as arquivo:
        return tomllib.load(arquivo)


def test_tema_do_streamlit_bate_com_o_do_grafico():
    """As cores do chrome e as do dado saem do mesmo lugar.

    `.streamlit/config.toml` pinta a página e `analise/estilo.py` pinta o
    gráfico. São dois arquivos, duas linguagens e dois momentos de carga, e a
    falha que isso produz é a pior de diagnosticar: o gráfico com um fundo e a
    página com outro, um retângulo de tom ligeiramente diferente no meio da
    tela, que ninguém reporta como bug porque parece de propósito.
    """
    from analise import estilo

    tema = _config_do_tema()["theme"]

    assert tema["base"] == "dark"
    assert tema["backgroundColor"] == estilo.SUPERFICIE
    assert tema["secondaryBackgroundColor"] == estilo.SUPERFICIE_ELEVADA
    assert tema["textColor"] == estilo.TINTA
    assert tema["borderColor"] == estilo.GRADE
    # Os dois azuis: preenchimento é a marca, texto é a versão legível dela.
    assert tema["primaryColor"] == estilo.AZUL_MARCA
    assert tema["linkColor"] == estilo.AZUL
    assert tema["chartCategoricalColors"] == list(estilo.CATEGORICAS)


def test_fontes_da_marca_existem_no_repositorio():
    """Fonte que não baixa não avisa: o navegador cai para a próxima da pilha.

    O sintoma é o app inteiro renderizado numa fonte de sistema, que é
    exatamente o que ele parecia antes de ter identidade — por isso passa
    despercebido. Este teste confere que o arquivo apontado por cada
    `[[theme.fontFaces]]` está mesmo no repositório, e que a família declarada é
    a que `estilo` pede.
    """
    from analise import estilo

    faces = {face["family"]: face for face in _config_do_tema()["theme"]["fontFaces"]}
    assert set(faces) == {estilo.FONTE[0], estilo.FONTE_MIUDA[0]}

    for familia, face in faces.items():
        caminho = RAIZ / face["url"]
        assert caminho.is_file(), f"{familia}: {face['url']} não existe"
        assert caminho.stat().st_size > 10_000, (
            f"{familia}: {caminho.name} tem {caminho.stat().st_size} bytes — "
            "parece uma página de erro salva com nome de fonte"
        )

    # O app só serve `app/static/` se isto estiver ligado, e sem ele as duas
    # URLs acima respondem 404 — com o mesmo silêncio de sempre.
    assert _config_do_tema()["server"]["enableStaticServing"] is True
