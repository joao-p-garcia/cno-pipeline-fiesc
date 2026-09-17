"""DAG de orquestração do pipeline CNO.

A DAG é deliberadamente fina: ela encadeia os mesmos comandos que qualquer
pessoa roda na mão (`cno extract`, `cno transform`, `cno validate`) e não contém
regra de negócio nenhuma. Isso mantém a lógica testável fora do Airflow — a
suíte de 65 testes roda sem subir scheduler — e garante que reproduzir uma falha
de produção seja copiar e colar um comando.

**O pipeline é invocado como subprocesso, não importado.** Os dois pacotes até
convivem no mesmo ambiente — verificado, `pip check` passa limpo —, mas a
fronteira de processo dá duas coisas que a de import não dá: o pipeline pode ser
atualizado sem reinstalar o Airflow, e a etapa que falha devolve um código de
saída em vez de uma exceção que a DAG teria de saber interpretar. O contrato
entre eles é a linha de comando e um JSON, não a árvore de dependências.

**Não há sensor de novidade, e é de propósito.** A tentação seria colocar um
ShortCircuit checando o ETag antes de baixar — mas o `cno extract` já faz isso
internamente e devolve em menos de um segundo quando não há publicação nova.
Um gate na DAG duplicaria a regra em dois lugares e criaria o risco de pular
etapas a jusante que ainda não rodaram (extração feita, tratamento não). A
idempotência vive nas etapas; a DAG só as encadeia.
"""

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
TIMEOUTS = {"extract": 60 * 30, "transform": 60 * 20, "validate": 60 * 10}


def executar_etapa(etapa: str, *argumentos: str) -> dict:
    """Roda um comando do pipeline e devolve o resumo em JSON.

    O `stdout` traz só o JSON e o `stderr` traz os logs, então dá para parsear
    a saída sem filtrar. Em caso de falha, o stderr vai para o log da task —
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
        # Falha de regra de negócio (validação reprovada, pacote inválido) não
        # melhora com nova tentativa: marca como falha definitiva.
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
    # A Receita publica de forma irregular; uma passada diária de madrugada é
    # barata (quando não há novidade a DAG inteira leva segundos) e garante que
    # a camada tratada nunca fique muitos dias atrás da fonte.
    schedule="0 4 * * *",
    start_date=datetime(2026, 9, 1),
    # A fonte expõe apenas a publicação corrente, sem histórico: não existe
    # backfill possível, e tentar um só produziria N execuções do mesmo dado.
    catchup=False,
    # Duas execuções simultâneas disputariam os mesmos diretórios de dados.
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
        # Única etapa que depende de rede. O download é resumível, então uma
        # nova tentativa continua de onde parou em vez de recomeçar.
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
        """Materializa a camada tratada em parquet tipado.

        Recebe o snapshot da etapa anterior em vez de resolver "o mais recente"
        por conta própria: se a Receita publicar no meio da execução, a DAG
        continua trabalhando no mesmo dado do começo ao fim.
        """
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
        """Confere o contrato da camada tratada e reconcilia com a fonte.

        Reprovação derruba a execução: é preferível a DAG falhar visivelmente a
        entregar uma camada tratada em que ninguém pode confiar.
        """
        resumo = executar_etapa("validate", "--snapshot", snapshot_id)
        for aviso in resumo["avisos"]:
            log.warning("aviso: %s (%s ocorrências)", aviso["regra"], aviso["violacoes"])
        log.info("validação aprovada para o snapshot %s", snapshot_id)
        return resumo

    validar(tratar(extrair()))


cno_pipeline()
