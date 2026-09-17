"""Etapa de extração: baixa o pacote da Receita e materializa a camada raw."""

from .cno import ErroDeExtracao, ResultadoExtracao, executar_extracao
from .manifest import Manifest, carregar_manifest, carregar_ultimo
from .source import ErroDeFonte, HttpSource, RemoteInfo

__all__ = [
    "ErroDeExtracao",
    "ErroDeFonte",
    "HttpSource",
    "Manifest",
    "RemoteInfo",
    "ResultadoExtracao",
    "carregar_manifest",
    "carregar_ultimo",
    "executar_extracao",
]
