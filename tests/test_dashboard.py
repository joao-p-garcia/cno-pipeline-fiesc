"""Testes do dashboard, sem navegador.

O `AppTest` do próprio Streamlit executa o script do app num runtime de mentira e
devolve os elementos que ele produziu. É o que permite tratar o dashboard como
código testável em vez de "abre e vê se aparece" — e o que pega a classe de erro
mais comum aqui: uma coluna renomeada na camada curada que só quebraria quando
alguém clicasse na quarta seção.

As seis seções são exercitadas uma a uma, sobre a camada sintética.
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
SECOES = ("fonte", "tabelas", "nulos", "area", "geo", "tempo", "camadas", "conclusoes")


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


@pytest.mark.parametrize("secao", SECOES)
def test_secao_renderiza_sem_excecao(secao, camada_curada, tmp_path):
    app = _rodar(secao, tmp_path)
    assert not app.exception, [str(e.value) for e in app.exception]
    assert app.markdown, "a seção não escreveu nada"


def test_app_inteiro_sobe(camada_curada, tmp_path):
    """A navegação em si: oito páginas, e nenhuma pode colidir de URL."""
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
