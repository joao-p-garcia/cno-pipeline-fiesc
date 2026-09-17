"""Etapa de validação: confere o contrato da camada tratada e reconcilia com a fonte."""

from .executor import (
    ErroDeValidacao,
    Reconciliacao,
    Relatorio,
    ResultadoRegra,
    executar_validacao,
)
from .regras import REGRAS, Regra, Severidade

__all__ = [
    "REGRAS",
    "ErroDeValidacao",
    "Reconciliacao",
    "Regra",
    "Relatorio",
    "ResultadoRegra",
    "Severidade",
    "executar_validacao",
]
