# Testes do contrato de caminhos entre a imagem, o compose e a DAG.

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DOCKERFILE = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
DAG = (RAIZ / "dags" / "cno_pipeline_dag.py").read_text(encoding="utf-8")


def _env_do_dockerfile(nome: str) -> str:
    """Lê o valor de uma variável declarada em `ENV` no Dockerfile."""
    achado = re.search(rf"^\s*(?:ENV\s+)?{nome}=(\S+)", DOCKERFILE, re.MULTILINE)
    assert achado, f"{nome} não está declarado no Dockerfile"
    return achado.group(1)


def _default_da_dag(nome: str) -> str:
    """Lê o fallback que a DAG usa quando a variável não vem do ambiente."""
    achado = re.search(rf'os\.environ\.get\(\s*"{nome}"\s*,\s*"([^"]+)"\s*\)', DAG)
    assert achado, f"a DAG não tem default para {nome}"
    return achado.group(1)


def test_cno_bin_da_imagem_e_o_que_a_dag_procura():
    """O executável instalado pela imagem tem de ser o que a DAG invoca."""
    assert _env_do_dockerfile("CNO_BIN") == _default_da_dag("CNO_BIN")


def test_cno_bin_fica_dentro_do_venv_que_o_dockerfile_cria():
    caminho = _env_do_dockerfile("CNO_BIN")
    venv = caminho.rsplit("/bin/", 1)[0]
    assert f"python -m venv {venv}" in DOCKERFILE
    assert f"{venv}/bin/pip install" in DOCKERFILE


def test_volume_de_dados_monta_onde_o_pipeline_escreve():
    """O volume nomeado precisa cair exatamente em CNO_DATA_DIR."""
    data_dir = _env_do_dockerfile("CNO_DATA_DIR")
    assert f"cno-dados:{data_dir}" in COMPOSE


def test_diretorio_de_dados_nasce_com_dono_airflow():
    """Sem o `install -d -o airflow`, o ponto de montagem nasce como root."""
    data_dir = _env_do_dockerfile("CNO_DATA_DIR")
    achado = re.search(r"^RUN install -d -o airflow -g root .*$", DOCKERFILE, re.MULTILINE)
    assert achado, "o Dockerfile não cria os diretórios do pipeline com dono airflow"
    assert data_dir in achado.group(0)


@pytest.mark.parametrize("caminho", ["data/", "dados_raw/", ".venv/", ".git/"])
def test_contexto_de_build_ignora_os_diretorios_pesados(caminho):
    """Juntos passam de 2 GB; sem isto cada build os copiaria antes de começar."""
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert caminho in [linha.strip() for linha in ignorados]
