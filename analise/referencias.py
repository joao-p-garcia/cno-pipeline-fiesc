"""Ponte entre a camada curada e a tabela de referência do IBGE.

Este módulo existe para que **o notebook e o Streamlit usem exatamente a mesma
definição de junção**. Se cada um normalizasse o nome do município do seu jeito,
os dois divergiriam num município qualquer e ninguém perceberia — é o mesmo
motivo de os marts existirem em vez de o app agregar por conta própria.

A junção é por `(UF, nome normalizado)`, não pelo código do município: a Receita
usa TOM de 4 dígitos e o IBGE usa código de 7, e a de-para entre os dois não tem
fonte canônica estável. Medido na base real, normalizar (maiúscula, sem acento,
sem hífen e apóstrofo) casa **5.555 de 5.572 (99,7%)**; os 17 que sobram estão em
`correcoes_municipios.csv`, escritos à mão e auditáveis linha a linha.

Trazer a tabela TOM de 5.570 linhas de um terceiro não evitaria esse trabalho —
só o esconderia num arquivo que não dá para revisar. **Você não evita a de-para;
você escolhe o tamanho dela.**
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent

ARQUIVO_MUNICIPIOS = AQUI / "municipios.csv"
ARQUIVO_CORRECOES = AQUI / "correcoes_municipios.csv"
ARQUIVO_MALHA = AQUI / "malha_municipios.geojson.gz"
ARQUIVO_META = AQUI / "municipios.meta.json"


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
    """Nome da coluna de população, que carrega o ano: `populacao_2026`.

    A safra vai no nome de propósito. Quem escrever `populacao` recebe erro de
    coluna inexistente em vez de dividir obras de 2026 por um denominador de
    outra época sem perceber.
    """
    return f"populacao_{metadados()['safra_populacao']}"


def dias_ate_vencer() -> int:
    meta = metadados()
    return (date.fromisoformat(meta["valido_ate"]) - datetime.now().date()).days


def sql_normalizar(coluna: str) -> str:
    """Normalização usada nos dois lados da junção.

    Maiúscula, sem acento, e hífen e apóstrofo viram espaço — que é o conjunto
    mínimo que resolve `Sant'Ana`/`SANTANA` e `Biritiba-Mirim`/`BIRITIBA MIRIM`
    sem colapsar nomes que são de fato diferentes.
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

    A correção tem precedência sobre a junção por nome: quando o município está
    na tabela de correções, é o código de lá que vale. `LEFT JOIN` de propósito —
    município que não casa continua na saída com os campos do IBGE nulos, em vez
    de desaparecer da contagem sem aviso.
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
