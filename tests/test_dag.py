"""Testes da DAG.

Só rodam onde o Airflow está instalado — que é o ambiente do orquestrador, não o
do pipeline. O `importorskip` faz a suíte principal continuar passando num venv
sem Airflow, e `make test-dag` roda estes aqui no venv certo.

O que se testa aqui é o encadeamento e a política de retry, não a regra de
negócio: essa já é coberta pelos testes das etapas, sem precisar de scheduler.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("airflow", reason="requer o venv do Airflow")

from airflow.sdk.exceptions import AirflowFailException  # noqa: E402

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"
sys.path.insert(0, str(DAGS_DIR))

import cno_pipeline_dag as modulo  # noqa: E402


@pytest.fixture
def dag():
    """Carrega a DAG como o scheduler carregaria, a partir da pasta `dags/`.

    Usar o `DagBag` em vez de importar o módulo direto é o que faz o teste pegar
    erro de parsing — que é como a maioria das DAGs quebra na prática.
    """
    from airflow.models import DagBag

    bag = DagBag(dag_folder=str(DAGS_DIR))
    assert not bag.import_errors, f"DAG não carregou: {bag.import_errors}"
    return bag.get_dag("cno_pipeline")


# -- estrutura ------------------------------------------------------------


def test_dag_carrega_sem_erro(dag):
    assert dag is not None
    assert dag.dag_id == "cno_pipeline"


def test_encadeamento_das_etapas(dag):
    """extrair -> tratar -> validar, nessa ordem e sem ramificação."""
    assert set(dag.task_ids) == {"extrair", "tratar", "validar"}

    assert dag.get_task("extrair").downstream_task_ids == {"tratar"}
    assert dag.get_task("tratar").downstream_task_ids == {"validar"}
    assert dag.get_task("validar").downstream_task_ids == set()


def test_so_a_extracao_tem_retry(dag):
    """Rede merece nova tentativa; etapa determinística, não.

    `transform` e `validate` são funções puras do dado de entrada: se falharam,
    falharão de novo. Retentar só multiplicaria o mesmo erro no log.
    """
    assert dag.get_task("extrair").retries == 3
    assert dag.get_task("tratar").retries == 0
    assert dag.get_task("validar").retries == 0


def test_nao_faz_backfill(dag):
    """A fonte só expõe a publicação corrente; backfill não faria sentido."""
    assert dag.catchup is False


def test_execucao_unica_por_vez(dag):
    """Duas execuções simultâneas disputariam os mesmos diretórios de dados."""
    assert dag.max_active_runs == 1


# -- o invocador do pipeline ----------------------------------------------


def _fingir_processo(monkeypatch, *, returncode: int, stdout: str, stderr: str = ""):
    def falso_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )

    monkeypatch.setattr(modulo.subprocess, "run", falso_run)


def test_executar_etapa_devolve_o_json(monkeypatch):
    _fingir_processo(
        monkeypatch,
        returncode=0,
        stdout=json.dumps({"etapa": "extract", "snapshot_id": "2026-09-12"}),
    )

    resumo = modulo.executar_etapa("extract")

    assert resumo["snapshot_id"] == "2026-09-12"


def test_executar_etapa_ignora_ruido_antes_do_json(monkeypatch):
    """Só a última linha do stdout é o resumo; o resto é ruído tolerável."""
    _fingir_processo(
        monkeypatch,
        returncode=0,
        stdout='aviso qualquer\n{"snapshot_id": "2026-09-12"}',
    )

    assert modulo.executar_etapa("extract")["snapshot_id"] == "2026-09-12"


def test_codigo_de_saida_nao_zero_falha_sem_retentar(monkeypatch):
    """Validação reprovada não melhora na segunda tentativa."""
    _fingir_processo(monkeypatch, returncode=1, stdout="", stderr="reprovado")

    with pytest.raises(AirflowFailException, match="código 1"):
        modulo.executar_etapa("validate")


def test_json_invalido_falha_explicitamente(monkeypatch):
    """Saída ilegível é falha, não sucesso silencioso com dicionário vazio."""
    _fingir_processo(monkeypatch, returncode=0, stdout="isto não é json")

    with pytest.raises(AirflowFailException, match="não devolveu JSON"):
        modulo.executar_etapa("transform")


def test_executavel_ausente_da_mensagem_acionavel(monkeypatch):
    def explodir(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(modulo.subprocess, "run", explodir)

    with pytest.raises(AirflowFailException, match="CNO_BIN"):
        modulo.executar_etapa("extract")


def test_timeout_vira_falha_definitiva(monkeypatch):
    def estourar(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="cno", timeout=1)

    monkeypatch.setattr(modulo.subprocess, "run", estourar)

    with pytest.raises(AirflowFailException, match="tempo limite"):
        modulo.executar_etapa("extract")
