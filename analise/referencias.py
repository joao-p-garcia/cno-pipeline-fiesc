"""Ponte entre a camada curada e a tabela de referência do IBGE.

A junção é por `(UF, nome normalizado)`, porque a Receita usa código TOM de 4
dígitos e o IBGE usa código de 7. Normalizar casa 5.555 de 5.572 municípios
(99,7%), e os 17 restantes estão em `correcoes_municipios.csv`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# Os quatro artefatos que `construir_municipios.py` gera.
ARQUIVO_MUNICIPIOS = AQUI / "municipios.csv"
ARQUIVO_CORRECOES = AQUI / "correcoes_municipios.csv"
ARQUIVO_MALHA = AQUI / "malha_municipios.geojson.gz"
ARQUIVO_META = AQUI / "municipios.meta.json"

# O código do IBGE começa com dois dígitos que identificam a UF.
TAMANHO_PREFIXO_UF = 2


class ReferenciaAusente(FileNotFoundError):
    """A tabela de referência não foi gerada."""


def _caminho(arquivo: Path) -> str:
    if not arquivo.is_file():
        raise ReferenciaAusente(
            f"{arquivo.name} não existe. Gere com:\n    python analise/construir_municipios.py"
        )
    return str(arquivo).replace("\\", "/")


def metadados() -> dict:
    """Safra, data de geração e validade. O app mostra isso ao lado dos números."""
    return json.loads(Path(_caminho(ARQUIVO_META)).read_text(encoding="utf-8"))


def coluna_populacao() -> str:
    """Nome da coluna de população, com o ano da safra (ex. `populacao_2026`)."""
    return f"populacao_{metadados()['safra_populacao']}"


# Sessenta dias dão duas execuções da DAG mensal antes do vencimento.
DIAS_AVISO_VALIDADE = 60


def dias_ate_vencer() -> int:
    """Dias até a safra da população vencer, em UTC. Negativo se já venceu.

    É a única implementação dessa conta; o gerador e a DAG chamam esta função.
    """
    meta = metadados()
    return (date.fromisoformat(meta["valido_ate"]) - datetime.now(UTC).date()).days


def sql_normalizar(coluna: str) -> str:
    """Normalização usada nos dois lados da junção.

    Maiúscula, sem acento, e hífen e apóstrofo viram espaço.
    """
    sem_pontuacao = f"regexp_replace(upper(strip_accents({coluna})), '[''`-]', ' ', 'g')"
    return f"trim(regexp_replace({sem_pontuacao}, ' +', ' ', 'g'))"


def registrar(con) -> None:
    """Cria as views `municipios` e `correcoes_municipios` na conexão DuckDB."""
    con.execute(f"""
        CREATE OR REPLACE VIEW municipios AS
        SELECT *, {sql_normalizar("nome")} AS chave
        FROM read_csv('{_caminho(ARQUIVO_MUNICIPIOS)}', header=true)
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW correcoes_municipios AS
        SELECT *, {sql_normalizar("nome_cno")} AS chave
        FROM read_csv('{_caminho(ARQUIVO_CORRECOES)}', header=true)
    """)


def sql_juntar(relacao: str, uf: str = "uf", nome: str = "nome_municipio") -> str:
    """Anexa os atributos do IBGE a uma relação que tenha UF e nome de município.

    A tabela de correções tem precedência sobre a junção por nome. `LEFT JOIN`,
    então município sem par continua na saída com os campos do IBGE nulos.
    """
    chave = sql_normalizar(f"r.{nome}")
    return f"""
SELECT
    r.*,
    coalesce(c.codigo_ibge, m.codigo_ibge)  AS codigo_ibge,
    coalesce(cm.nome, m.nome)               AS nome_ibge,
    coalesce(cm.regiao_imediata, m.regiao_imediata)           AS regiao_imediata,
    coalesce(cm.regiao_intermediaria, m.regiao_intermediaria) AS regiao_intermediaria,
    coalesce(cm.{coluna_populacao()}, m.{coluna_populacao()}) AS populacao,
    coalesce(cm.latitude, m.latitude)       AS latitude_municipio,
    coalesce(cm.longitude, m.longitude)     AS longitude_municipio,
    (c.codigo_ibge IS NOT NULL)             AS casou_por_correcao
FROM {relacao} r
LEFT JOIN correcoes_municipios c
       ON c.uf = r.{uf} AND c.chave = {chave}
LEFT JOIN municipios cm
       ON cm.codigo_ibge = c.codigo_ibge
LEFT JOIN municipios m
       ON m.uf = r.{uf} AND m.chave = {chave}
"""
