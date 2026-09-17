"""Etapa de tratamento: da camada raw para parquet tipado e pronto para análise."""

from .encoding import ErroDeTranscodificacao, transcodificar

__all__ = ["ErroDeTranscodificacao", "transcodificar"]
