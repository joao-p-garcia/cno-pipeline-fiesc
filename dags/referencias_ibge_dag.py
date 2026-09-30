"""DAG de vigilância da tabela de referência do IBGE.

A tabela de municípios (nome, UF, região, população, malha) fica fora do pipeline
do CNO, porque vem do IBGE e muda uma vez por ano.

Roda mensalmente, não acessa a rede, só lê a validade declarada em
`municipios.meta.json` e **falha quando os dados do IBGE vencem**. A falha é o
aviso para regerar a tabela e revisar as análises que dependem dela.
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
    """Carrega `analise/referencias.py` a partir do diretório instalado."""
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
    schedule="@monthly",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "observatorio",
        "depends_on_past": False,
        "email_on_failure": True,
    },
    tags=["ibge", "referencia", "observatorio"],
    doc_md=__doc__,
)
def referencias_ibge():
    @task(retries=0)
    def verificar_validade() -> dict:
        """Falha se a safra da população venceu."""
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
