"""DAG de orquestração do pipeline CNO."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta

from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowFailException

log = logging.getLogger(__name__)

# Caminho do executável do pipeline. Em container aponta para o venv próprio do
# pipeline; em desenvolvimento, para o `.venv` do repositório.
CNO_BIN = os.environ.get("CNO_BIN", "/opt/cno/.venv/bin/cno")

# Timeout por etapa. A extração é a única que depende de rede e de baixar
# 315 MB, por isso tem folga maior.
TIMEOUTS = {"extract": 60 * 30, "transform": 60 * 20, "validate": 60 * 10, "curate": 60 * 20}


def executar_etapa(etapa: str, *argumentos: str) -> dict:
    """Roda um comando do pipeline e devolve o resumo em JSON.

    O `stdout` traz só o JSON e o `stderr` traz os logs, então dá para parsear
    a saída sem filtrar. Em caso de falha, o stderr vai para o log da task,
    que é onde quem investiga vai procurar.
    """
    comando = [CNO_BIN, etapa, *argumentos, "--json"]
    log.info("executando: %s", " ".join(comando))

    try:
        processo = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=TIMEOUTS.get(etapa, 600),
            check=False,
            env={**os.environ, "CNO_LOG_JSON": "1"},
        )
    except FileNotFoundError as exc:
        raise AirflowFailException(
            f"executável do pipeline não encontrado em {CNO_BIN}; ajuste a variável CNO_BIN"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AirflowFailException(f"etapa {etapa} excedeu o tempo limite") from exc

    if processo.stderr:
        log.info("--- logs de %s ---\n%s", etapa, processo.stderr.strip())

    if processo.returncode != 0:
        raise AirflowFailException(f"etapa {etapa} falhou com código {processo.returncode}")

    try:
        return json.loads(processo.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise AirflowFailException(
            f"etapa {etapa} não devolveu JSON válido: {processo.stdout[:300]!r}"
        ) from exc


@dag(
    dag_id="cno_pipeline",
    description="Extrai, trata e valida a base do CNO da Receita Federal",
    schedule="0 4 * * *",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "observatorio",
        "depends_on_past": False,
        "email_on_failure": False,
    },
    tags=["cno", "receita-federal", "observatorio"],
    doc_md=__doc__,
)
def cno_pipeline():
    @task(
        retries=3,
        retry_delay=timedelta(minutes=5),
        retry_exponential_backoff=True,
    )
    def extrair() -> str:
        """Baixa e descompacta o snapshot corrente na camada raw."""
        resumo = executar_etapa("extract")
        log.info(
            "snapshot %s (%s)",
            resumo["snapshot_id"],
            "reaproveitado" if resumo["reaproveitado"] else "baixado agora",
        )
        return resumo["snapshot_id"]

    @task(retries=0)
    def tratar(snapshot_id: str) -> str:
        """Materializa a camada tratada em parquet tipado."""
        resumo = executar_etapa("transform", "--snapshot", snapshot_id)
        for tabela in resumo["tabelas"]:
            log.info(
                "%-9s %s linhas (%s duplicatas removidas)",
                tabela["nome"],
                f"{tabela['linhas_destino']:,}",
                f"{tabela['duplicatas_removidas']:,}",
            )
        return snapshot_id

    @task(retries=0)
    def validar(snapshot_id: str) -> dict:
        """Confere o contrato da camada tratada e reconcilia com a fonte."""
        resumo = executar_etapa("validate", "--snapshot", snapshot_id)
        for aviso in resumo["avisos"]:
            log.warning("aviso: %s (%s ocorrências)", aviso["regra"], aviso["violacoes"])
        log.info("validação aprovada para o snapshot %s", snapshot_id)
        return resumo

    @task(retries=0)
    def curar(relatorio: dict) -> dict:
        """Modela a camada curada e os marts que a análise e o dashboard leem."""
        snapshot_id = relatorio["snapshot_id"]
        resumo = executar_etapa("curate", "--snapshot", snapshot_id)
        geo = resumo["geocodificacao"]
        log.info(
            "geocodificação: %.1f%% (%s completos, %s curtos recuperados)",
            geo["cobertura"] * 100,
            f"{geo['completos']:,}",
            f"{geo['curtos_recuperados']:,}",
        )
        for tabela in resumo["tabelas"]:
            log.info("%-20s %s linhas", tabela["nome"], f"{tabela['linhas']:,}")
        return resumo

    curar(validar(tratar(extrair())))


cno_pipeline()
