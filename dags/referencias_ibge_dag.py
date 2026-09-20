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

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowSkipException

log = logging.getLogger(__name__)

# Onde a camada de análise foi instalada. No container a imagem traz `analise/`
# em /opt/cno/analise; em desenvolvimento, o diretório do repositório.
DIRETORIO_REFERENCIAS = Path(os.environ.get("CNO_REFERENCIAS_DIR", "/opt/cno/analise"))

# Quantos dias antes do vencimento a DAG começa a avisar no log. Não falha ainda:
# falhar cedo demais treina quem opera a ignorar o alerta.
ANTECEDENCIA_AVISO = 60


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
        caminho = DIRETORIO_REFERENCIAS / "municipios.meta.json"

        if not caminho.is_file():
            # Ausência não é falha: significa que a camada de análise não foi
            # instalada neste ambiente. Um pipeline de dados sem dashboard é uma
            # implantação legítima, e marcar isso como erro seria ruído.
            raise AirflowSkipException(
                f"{caminho} não existe; a camada de análise não está instalada aqui"
            )

        meta = json.loads(caminho.read_text(encoding="utf-8"))
        valido_ate = date.fromisoformat(meta["valido_ate"])
        dias = (valido_ate - datetime.now().date()).days

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

        if dias <= ANTECEDENCIA_AVISO:
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
