"""DAG de vigilância da tabela de referência do IBGE.

**É uma DAG separada de propósito, e essa separação é a decisão.**

A tabela de municípios (nome, UF, região, população, malha) fica fora do pipeline
do CNO: ela vem do IBGE, muda uma vez por ano e não torna nenhum número do
pipeline certo ou errado. Colocá-la como task da `cno_pipeline` criaria um
acoplamento de falha — uma indisponibilidade do IBGE derrubaria uma esteira que
não precisa do IBGE para nada.

Mas "fica fora" não pode virar "ninguém lembra". Dado com validade precisa ser
vigiado por máquina, não pela memória de quem estava no projeto há um ano. Esta
DAG é a vigilância: roda mensalmente, não busca nada na rede, só lê a validade
declarada em `municipios.meta.json` e **falha quando a safra vence** — e falha é
o que dispara o alerta do Airflow, que num deploy em nuvem é o canal que já
existe.

Sendo DAG separada, ela pode ficar vermelha o tempo que for sem afetar a
`cno_pipeline`. É exatamente o que se quer: o aviso é sobre a análise, não sobre
a esteira de dados.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowSkipException

log = logging.getLogger(__name__)

# Onde a camada de análise foi instalada. No container a imagem traz `analise/`
# em /opt/cno/analise; em desenvolvimento, o diretório do repositório.
DIRETORIO_REFERENCIAS = Path(os.environ.get("CNO_REFERENCIAS_DIR", "/opt/cno/analise"))


def _referencias():
    """Carrega `analise/referencias.py` a partir do diretório instalado.

    Por que `importlib` e não `import`: esta DAG roda no venv do **Airflow**, e
    `analise/` não é pacote instalado nele — ela vive ao lado, no ambiente do
    dashboard. O módulo é stdlib puro (json, datetime, pathlib), então carregá-lo
    por caminho não arrasta dependência nenhuma para dentro do Airflow. É o mesmo
    recurso que `tests/test_referencias.py` já usa.

    Por que carregar em vez de reimplementar: a DAG **refazia** a conta de
    validade. Havia três versões dela, e já discordavam — a DAG avisava com 60
    dias, o gerador com 30, e os dois usavam relógios diferentes. Agora a conta é
    uma só, e esta função só decide o que fazer com o número.
    """
    import importlib.util

    caminho = DIRETORIO_REFERENCIAS / "referencias.py"
    spec = importlib.util.spec_from_file_location("referencias_ibge_analise", caminho)
    if spec is None or spec.loader is None:  # pragma: no cover - caminho inválido
        raise RuntimeError(f"não foi possível carregar {caminho}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@dag(
    dag_id="referencias_ibge",
    description="Vigia a validade da tabela de municípios usada pela análise",
    # Mensal. A tabela vale um ano, então mensal garante que o vencimento seja
    # percebido em no máximo 30 dias — e custa doze execuções de milissegundos
    # por ano, que leem um arquivo JSON local.
    schedule="@monthly",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "observatorio",
        "depends_on_past": False,
        # Num deploy real, é isto que leva o aviso para quem precisa saber.
        "email_on_failure": True,
    },
    tags=["ibge", "referencia", "observatorio"],
    doc_md=__doc__,
)
def referencias_ibge():
    @task(retries=0)
    def verificar_validade() -> dict:
        """Falha se a safra da população venceu.

        Não faz requisição nenhuma: lê a validade que o próprio arquivo declara.
        Isso mantém a DAG imune a instabilidade do IBGE — ela vigia o nosso
        arquivo, não o serviço deles.
        """
        # Ausência não é falha: significa que a camada de análise não foi
        # instalada neste ambiente. Um pipeline de dados sem dashboard é uma
        # implantação legítima, e marcar isso como erro seria ruído.
        modulo = DIRETORIO_REFERENCIAS / "referencias.py"
        if not modulo.is_file():
            raise AirflowSkipException(
                f"{modulo} não existe; a camada de análise não está instalada aqui"
            )

        referencias = _referencias()
        if not referencias.ARQUIVO_META.is_file():
            raise AirflowSkipException(
                f"{referencias.ARQUIVO_META} não existe; a tabela nunca foi gerada aqui"
            )

        meta = referencias.metadados()
        dias = referencias.dias_ate_vencer()

        log.info(
            "safra da população: %s (gerada em %s, válida até %s)",
            meta["safra_populacao"],
            meta["gerado_em"],
            meta["valido_ate"],
        )

        if dias < 0:
            raise RuntimeError(
                f"A tabela de municípios do IBGE venceu há {-dias} dias "
                f"(safra {meta['safra_populacao']}, válida até {meta['valido_ate']}).\n"
                "O IBGE publica nova estimativa populacional por volta de agosto.\n"
                "Regere e commite:\n"
                "    python analise/construir_municipios.py\n"
                "Enquanto não for regerada, todo número per capita da análise usa "
                "um denominador vencido."
            )

        if dias <= referencias.DIAS_AVISO_VALIDADE:
            log.warning(
                "a tabela de municípios vence em %d dias — vale regerar antes que "
                "alguém apresente um número com denominador velho",
                dias,
            )
        else:
            log.info("válida por mais %d dias", dias)

        return {"safra": meta["safra_populacao"], "dias_restantes": dias}

    verificar_validade()


referencias_ibge()
