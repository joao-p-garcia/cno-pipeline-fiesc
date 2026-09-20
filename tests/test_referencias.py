"""Testes da tabela de referência do IBGE.

Ela fica fora do pipeline e é atualizada uma vez por ano — exatamente o perfil de
arquivo que apodrece sem ninguém notar. Estes testes não checam o IBGE: checam a
**coerência interna** do que está versionado, que é o que dá para garantir sem
rede e o que de fato quebra quando alguém edita as correções à mão.

Não há chamada de rede aqui. A suíte continua rodando offline.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

RAIZ = Path(__file__).resolve().parents[1]
ANALISE = RAIZ / "analise"

pytestmark = pytest.mark.skipif(
    not (ANALISE / "municipios.csv").is_file(),
    reason="tabela de referência não gerada (python analise/construir_municipios.py)",
)


def _carregar_modulo():
    """Importa `analise/referencias.py`, que não é pacote instalado."""
    spec = importlib.util.spec_from_file_location("referencias", ANALISE / "referencias.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _linhas(arquivo: Path) -> list[dict]:
    with arquivo.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def municipios() -> list[dict]:
    return _linhas(ANALISE / "municipios.csv")


@pytest.fixture(scope="module")
def correcoes() -> list[dict]:
    return _linhas(ANALISE / "correcoes_municipios.csv")


@pytest.fixture(scope="module")
def meta() -> dict:
    return json.loads((ANALISE / "municipios.meta.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Coerência da tabela
# ---------------------------------------------------------------------------


def test_codigo_ibge_e_chave_unica(municipios):
    codigos = [m["codigo_ibge"] for m in municipios]
    assert len(codigos) == len(set(codigos))
    assert all(len(c) == 7 and c.isdigit() for c in codigos)


def test_a_coluna_de_populacao_carrega_a_safra(municipios, meta):
    """`populacao_2026`, nunca `populacao`.

    Quem escrever o nome genérico recebe erro de coluna inexistente em vez de
    dividir obras de hoje por um denominador de outra época sem perceber.
    """
    coluna = f"populacao_{meta['safra_populacao']}"
    assert coluna in municipios[0]
    assert "populacao" not in municipios[0]


def test_todo_municipio_tem_populacao_e_uf(municipios, meta):
    sem_populacao = [m for m in municipios if not m[f"populacao_{meta['safra_populacao']}"].strip()]
    assert len(sem_populacao) == meta["sem_populacao"]
    assert all(len(m["uf"]) == 2 for m in municipios)


def test_o_metadado_bate_com_o_arquivo(municipios, meta):
    assert meta["municipios"] == len(municipios)
    assert meta["valido_ate"] > meta["gerado_em"]


# ---------------------------------------------------------------------------
# Coerência das correções, que são escritas à mão
# ---------------------------------------------------------------------------


def test_correcoes_apontam_para_municipios_que_existem(correcoes, municipios):
    """Correção que aponta para código inexistente some da análise em silêncio."""
    por_codigo = {m["codigo_ibge"]: m for m in municipios}
    for linha in correcoes:
        alvo = por_codigo.get(linha["codigo_ibge"])
        assert alvo is not None, f"{linha['nome_cno']}: código {linha['codigo_ibge']} não existe"
        assert alvo["uf"] == linha["uf"], f"{linha['nome_cno']}: UF diverge do IBGE"
        assert alvo["nome"] == linha["nome_ibge"], (
            f"{linha['nome_cno']}: nome do IBGE mudou para {alvo['nome']!r}"
        )


def test_nao_ha_correcao_duplicada(correcoes):
    chaves = [(linha["uf"], linha["nome_cno"]) for linha in correcoes]
    assert len(chaves) == len(set(chaves))


def test_toda_correcao_tem_motivo(correcoes):
    """O motivo é o que torna a tabela revisável por outra pessoa."""
    assert correcoes
    assert all(linha["motivo"].strip() for linha in correcoes)


def test_correcao_so_existe_para_quem_nao_casa_por_nome(correcoes):
    """Correção redundante é dívida: se o nome já casa, a linha não deveria estar aqui.

    Sem esta checagem, a tabela cresce com entradas que ninguém ousa remover
    porque ninguém sabe mais se ainda são necessárias.
    """
    referencias = _carregar_modulo()
    con = duckdb.connect()
    referencias.registrar(con)

    redundantes = con.execute("""
        SELECT c.nome_cno, m.nome
        FROM correcoes_municipios c
        JOIN municipios m ON m.uf = c.uf AND m.chave = c.chave
    """).fetchall()
    assert not redundantes, f"correções desnecessárias, o nome já casa: {redundantes}"


def test_a_normalizacao_resolve_acento_apostrofo_e_hifen():
    referencias = _carregar_modulo()
    con = duckdb.connect()
    expressao = referencias.sql_normalizar("nome")
    resultado = dict(
        con.execute(f"""
            SELECT nome, {expressao} FROM (VALUES
                ('Sant''Ana do Livramento'),
                ('Biritiba-Mirim'),
                ('São Valério'),
                ('  Espaço   Duplo  ')
            ) t(nome)
        """).fetchall()
    )
    assert resultado["Sant'Ana do Livramento"] == "SANT ANA DO LIVRAMENTO"
    assert resultado["Biritiba-Mirim"] == "BIRITIBA MIRIM"
    assert resultado["São Valério"] == "SAO VALERIO"
    assert resultado["  Espaço   Duplo  "] == "ESPACO DUPLO"
