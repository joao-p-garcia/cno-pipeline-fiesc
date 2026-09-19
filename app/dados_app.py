"""Porta de entrada do dashboard para a camada curada.

Uma função só faz consulta, e ela é a única coisa cacheada. O Streamlit reexecuta
o script inteiro a cada clique; sem cache, cada filtro pagaria a varredura de novo
e o app pareceria quebrado.

**O app não tem SQL.** Toda consulta mora em `analise/dados.py`, que o notebook
também usa. Aqui só se escolhe qual pergunta fazer e se guarda a resposta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from analise import dados, estilo, malha, referencias  # noqa: E402


@st.cache_resource(show_spinner="abrindo a camada curada…")
def conexao() -> dados.Curada:
    """Uma conexão DuckDB por processo, viva entre reexecuções do script."""
    estilo.registrar_altair()
    return dados.abrir()


@st.cache_data(ttl=3600, show_spinner=False)
def consultar(pergunta: str, **filtros):
    """Executa uma das funções de `analise.dados` e guarda o resultado.

    O nome da função entra como texto porque o Streamlit precisa de argumentos
    hasheáveis para indexar o cache — a conexão não é, e é resolvida aqui dentro.
    """
    return getattr(dados, pergunta)(conexao(), **filtros)


@st.cache_data(ttl=3600, show_spinner=False)
def valor(sql: str):
    """Escapatória para um número avulso que não justifica uma função nomeada."""
    return conexao().valor(sql)


@st.cache_data(show_spinner=False)
def consultar_amostra() -> list[bytes]:
    """As linhas cruas do `cno.csv`, em bytes, como a Receita publica."""
    return dados.amostra_bruta()


@st.cache_data(show_spinner=False)
def decodificar_amostra(encoding: str) -> list[str]:
    """A mesma amostra lida em cp1252 ou em latin-1 — a demonstração da seção 1."""
    return dados.decodificar(dados.amostra_bruta(), encoding)


@st.cache_data(show_spinner=False)
def contornos_uf(prefixo: str) -> dict:
    """Malha municipal de uma UF, no formato que o Altair consome."""
    return malha.por_prefixo(prefixo)


def metadados_referencia() -> dict | None:
    """Safra e validade da tabela do IBGE, ou `None` se ela não foi gerada."""
    return referencias.metadados() if dados.tem_referencias() else None
