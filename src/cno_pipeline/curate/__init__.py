"""Etapa de curadoria: da staging fiel à origem para o modelo que a análise usa."""

from .curated import (
    ErroDeCuradoria,
    MetricasGeo,
    MetricasTabela,
    ResultadoCuradoria,
    executar_curadoria,
)
from .dominios import FAIXAS_AREA_M2, PRIMEIRO_ANO_COMPARAVEL, SECOES_CNAE, secao_cnae

__all__ = [
    "FAIXAS_AREA_M2",
    "PRIMEIRO_ANO_COMPARAVEL",
    "SECOES_CNAE",
    "ErroDeCuradoria",
    "MetricasGeo",
    "MetricasTabela",
    "ResultadoCuradoria",
    "executar_curadoria",
    "secao_cnae",
]
