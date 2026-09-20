"""Testes da DAG.

Só rodam onde o Airflow está instalado — que é o ambiente do orquestrador, não o
do pipeline. O `importorskip` faz a suíte principal continuar passando num venv
sem Airflow, e `make test-dag` roda estes aqui no venv certo.

O que se testa aqui é o encadeamento e a política de retry, não a regra de
negócio: essa já é coberta pelos testes das etapas, sem precisar de scheduler.
"""

from __future__ import annotations

import json
import shutil
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
    """extrair -> tratar -> validar -> curar, nessa ordem e sem ramificação.

    A curadoria vem depois da validação de propósito: é ela que alimenta o
    relatório e o dashboard, e publicar número em cima de dado reprovado é pior
    do que não publicar número nenhum.
    """
    assert set(dag.task_ids) == {"extrair", "tratar", "validar", "curar"}

    assert dag.get_task("extrair").downstream_task_ids == {"tratar"}
    assert dag.get_task("tratar").downstream_task_ids == {"validar"}
    assert dag.get_task("validar").downstream_task_ids == {"curar"}
    assert dag.get_task("curar").downstream_task_ids == set()


def test_so_a_extracao_tem_retry(dag):
    """Rede merece nova tentativa; etapa determinística, não.

    `transform` e `validate` são funções puras do dado de entrada: se falharam,
    falharão de novo. Retentar só multiplicaria o mesmo erro no log.
    """
    assert dag.get_task("extrair").retries == 3
    assert dag.get_task("tratar").retries == 0
    assert dag.get_task("validar").retries == 0
    assert dag.get_task("curar").retries == 0


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


# ---------------------------------------------------------------------------
# DAG de vigilância da referência do IBGE
# ---------------------------------------------------------------------------


@pytest.fixture
def dag_ibge():
    from airflow.models import DagBag

    bag = DagBag(dag_folder=str(DAGS_DIR))
    assert not bag.import_errors, f"DAG não carregou: {bag.import_errors}"
    return bag.get_dag("referencias_ibge")


def _verificador(dag_ibge, monkeypatch, diretorio):
    """Devolve a função da task, com o diretório de referências redirecionado.

    O `DagBag` importa o arquivo da DAG sob um nome próprio, então o módulo que
    ele carregou **não é** o que um `import` normal traz. Patchear pelo import
    não alcança a cópia que a task usa; alcançar os globais da própria função é
    o que funciona, e é a razão deste helper existir.
    """
    funcao = dag_ibge.get_task("verificar_validade").python_callable
    monkeypatch.setitem(funcao.__globals__, "DIRETORIO_REFERENCIAS", diretorio)
    return funcao


def _instalar_referencias(diretorio: Path) -> None:
    """Copia `analise/referencias.py` para o diretório, como a imagem faz.

    A DAG deixou de refazer a conta de validade e passou a chamar
    `referencias.dias_ate_vencer()`. Com isso o diretório de referências precisa
    conter o módulo, não só o JSON — que é como ele existe de verdade, no
    repositório e em `/opt/cno/analise` dentro da imagem. Um diretório com
    `municipios.meta.json` e sem `referencias.py` não acontece em lugar nenhum.
    """
    origem = Path(__file__).resolve().parents[1] / "analise" / "referencias.py"
    shutil.copy(origem, diretorio / "referencias.py")


def test_dag_do_ibge_e_separada_e_minima(dag_ibge):
    """Separada da `cno_pipeline` de propósito: não pode derrubar a pipeline.

    Uma task só, sem rede, lendo um arquivo local. Se esta DAG ficar vermelha, o
    pipeline de dados continua verde — que é exatamente a divisão pretendida.
    """
    assert dag_ibge is not None
    assert set(dag_ibge.task_ids) == {"verificar_validade"}
    assert dag_ibge.dag_id != "cno_pipeline"


def test_referencia_ausente_e_skip_nao_falha(dag_ibge, tmp_path, monkeypatch):
    """Sem camada de análise instalada, a DAG pula em vez de ficar vermelha.

    Um pipeline de dados sem dashboard é implantação legítima; marcar isso como
    erro treinaria quem opera a ignorar o alerta — que é o oposto do objetivo.

    O diretório vazio representa isso com mais fidelidade do que antes: sem
    `referencias.py`, a camada de análise de fato não está ali.
    """
    from airflow.sdk.exceptions import AirflowSkipException

    with pytest.raises(AirflowSkipException):
        _verificador(dag_ibge, monkeypatch, tmp_path)()


def test_safra_vencida_falha_com_instrucao(dag_ibge, tmp_path, monkeypatch):
    """Vencida tem de falhar: é a falha que dispara o alerta do Airflow."""
    _instalar_referencias(tmp_path)
    (tmp_path / "municipios.meta.json").write_text(
        json.dumps(
            {
                "gerado_em": "2020-01-01",
                "valido_ate": "2021-01-01",
                "safra_populacao": "2020",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError) as erro:
        _verificador(dag_ibge, monkeypatch, tmp_path)()
    # A mensagem tem de dizer o que fazer, não só que quebrou.
    assert "construir_municipios.py" in str(erro.value)


def test_safra_valida_passa(dag_ibge, tmp_path, monkeypatch):
    from datetime import date, timedelta

    _instalar_referencias(tmp_path)
    futuro = (date.today() + timedelta(days=200)).isoformat()
    (tmp_path / "municipios.meta.json").write_text(
        json.dumps({"gerado_em": "2026-09-19", "valido_ate": futuro, "safra_populacao": "2026"}),
        encoding="utf-8",
    )
    resultado = _verificador(dag_ibge, monkeypatch, tmp_path)()
    assert resultado["safra"] == "2026"
    assert resultado["dias_restantes"] > 0
