"""Etapa de tratamento: da camada raw para parquet tipado e pronto para análise."""

from .encoding import ErroDeTranscodificacao, transcodificar
from .schema import TABELAS, TabelaSpec, tabela_por_nome
from .staging import (
    ErroDeStaging,
    MetricasTabela,
    ResultadoStaging,
    executar_staging,
)

__all__ = [
    "TABELAS",
    "ErroDeStaging",
    "ErroDeTranscodificacao",
    "MetricasTabela",
    "ResultadoStaging",
    "TabelaSpec",
    "executar_staging",
    "tabela_por_nome",
    "transcodificar",
]
