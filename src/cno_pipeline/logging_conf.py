"""Configuração de logging.

Saída em texto simples por padrão (legível no terminal) e em JSON quando
`CNO_LOG_JSON=1` — que é o formato útil quando o pipeline roda sob um
orquestrador e os logs vão para um coletor.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime


class FormatadorJson(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        dados = {
            "ts": datetime.fromtimestamp(registro.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": registro.levelname,
            "logger": registro.name,
            "msg": registro.getMessage(),
        }
        if registro.exc_info:
            dados["excecao"] = self.formatException(registro.exc_info)
        return json.dumps(dados, ensure_ascii=False)


def configurar_logging(verboso: bool = False) -> None:
    """Configura o root logger. Idempotente: chamar duas vezes não duplica saída."""
    nivel = logging.DEBUG if verboso else logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    if os.environ.get("CNO_LOG_JSON", "").strip() in {"1", "true", "yes"}:
        handler.setFormatter(FormatadorJson())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    raiz = logging.getLogger()
    for antigo in list(raiz.handlers):
        raiz.removeHandler(antigo)
    raiz.addHandler(handler)
    raiz.setLevel(nivel)

    # urllib3 loga cada retry em DEBUG; útil só quando estamos depurando rede.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
