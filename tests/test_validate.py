"""Testes da validação.

Boa parte deles injeta defeito de propósito na camada tratada. É o único jeito
de provar que a validação pega o problema — uma suíte que só verifica o caminho
feliz não distingue "está tudo certo" de "a regra não está sendo avaliada".
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from cno_pipeline.config import Settings
from cno_pipeline.transform.staging import executar_staging
from cno_pipeline.validate import ErroDeValidacao, executar_validacao
from cno_pipeline.validate.executor import _avaliar
from cno_pipeline.validate.regras import Regra, Severidade

from .dados_sinteticos import SNAPSHOT


def _particao(settings: Settings, tabela: str) -> Path:
    return settings.staging_dir / tabela / f"snapshot_date={SNAPSHOT}"


def _injetar(settings: Settings, tabela: str, transformacao: str = "") -> None:
    """Acrescenta uma linha defeituosa a uma tabela já materializada.

    Copia uma linha de um parquet existente para um arquivo novo **na mesma
    pasta**, opcionalmente alterando colunas. Fazer assim, em vez de reescrever
    a tabela, garante que o schema bate: em parquet particionado, `uf` e
    `snapshot_date` vivem no caminho do diretório e não dentro do arquivo.
    """
    arquivo = next(iter(_particao(settings, tabela).rglob("*.parquet")))
    colunas = f"* REPLACE ({transformacao})" if transformacao else "*"
    con = duckdb.connect()
    try:
        con.execute(f"""
            COPY (SELECT {colunas} FROM read_parquet('{arquivo}') LIMIT 1)
            TO '{arquivo.parent}/injetado.parquet' (FORMAT PARQUET)
        """)
    finally:
        con.close()


# -- caminho feliz --------------------------------------------------------


def test_dado_tratado_passa_na_validacao(camada_raw: Settings):
    executar_staging(camada_raw)
    relatorio = executar_validacao(camada_raw)

    assert relatorio.passou is True
    assert relatorio.erros == ()
    assert relatorio.snapshot_id == SNAPSHOT


def test_reconciliacao_bate_com_os_totais_da_fonte(camada_raw: Settings):
    """A única checagem que olha para fora do pipeline."""
    executar_staging(camada_raw)
    relatorio = executar_validacao(camada_raw)

    por_tabela = {r.tabela: r for r in relatorio.reconciliacoes}
    assert por_tabela["obras"].linhas_origem == 12
    assert por_tabela["obras"].total_oficial == 12
    assert por_tabela["obras"].confere is True

    # a reconciliação usa as linhas ANTES do dedup, que é o que a fonte conta
    areas = por_tabela["areas"]
    assert areas.linhas_origem == 4
    assert areas.total_oficial == 4
    assert areas.duplicatas_removidas == 1
    assert areas.linhas_tratadas == 3
    assert areas.confere is True


def test_avisos_nao_reprovam(camada_raw: Settings):
    """Sujeira conhecida da fonte é medida, não motivo de falha."""
    executar_staging(camada_raw)
    relatorio = executar_validacao(camada_raw)

    nomes = {a.nome for a in relatorio.avisos}
    assert "obras.area_plausivel" in nomes  # a obra de 555 bilhões de m²
    assert relatorio.passou is True


# -- detecção de defeitos -------------------------------------------------


def test_detecta_cno_duplicado(camada_raw: Settings):
    executar_staging(camada_raw)
    _injetar(camada_raw, "obras")  # duplica uma linha existente

    relatorio = executar_validacao(camada_raw)

    falhou = {e.nome for e in relatorio.erros}
    assert "obras.cno_unico" in falhou
    assert relatorio.passou is False


def test_detecta_area_orfa(camada_raw: Settings):
    """Área apontando para obra inexistente é quebra de integridade."""
    executar_staging(camada_raw)
    _injetar(camada_raw, "areas", "'999999999999' AS cno")

    relatorio = executar_validacao(camada_raw)

    falhou = {e.nome for e in relatorio.erros}
    assert "areas.cno_existe_em_obras" in falhou
    assert relatorio.passou is False


def test_relatorio_traz_exemplos_acionaveis(camada_raw: Settings):
    """Saber que há 3 violações não ajuda; saber quais ajuda."""
    executar_staging(camada_raw)
    _injetar(camada_raw, "obras")

    relatorio = executar_validacao(camada_raw)
    regra = next(e for e in relatorio.erros if e.nome == "obras.cno_unico")

    assert regra.exemplos
    assert "cno" in regra.exemplos[0]


def test_detecta_divergencia_de_reconciliacao(camada_raw: Settings):
    """Se a extração perdesse metade do arquivo, só a fonte denunciaria."""
    executar_staging(camada_raw)

    manifesto = camada_raw.staging_dir / "_manifests" / f"{SNAPSHOT}.json"
    dados = json.loads(manifesto.read_text(encoding="utf-8"))
    dados["totais_controle"]["cno"] = 99999
    manifesto.write_text(json.dumps(dados), encoding="utf-8")

    relatorio = executar_validacao(camada_raw)

    divergentes = {r.tabela for r in relatorio.reconciliacoes_divergentes}
    assert "obras" in divergentes
    assert relatorio.passou is False


# -- robustez da própria validação ---------------------------------------


def test_regra_quebrada_falha_alto(camada_raw: Settings):
    """Regra com SQL inválido não pode ser confundida com regra cumprida."""
    executar_staging(camada_raw)
    particao = _particao(camada_raw, "obras")
    regra = Regra(
        nome="regra.invalida",
        descricao="coluna que não existe",
        severidade=Severidade.ERRO,
        violacoes="SELECT * FROM {obras} WHERE coluna_inexistente = 1",
    )

    con = duckdb.connect()
    try:
        with pytest.raises(ErroDeValidacao, match="não pôde ser avaliada"):
            _avaliar(con, regra, {"obras": f"read_parquet('{particao}/**/*.parquet')"})
    finally:
        con.close()


def test_falha_clara_sem_camada_tratada(settings_staging: Settings):
    with pytest.raises(ErroDeValidacao, match="cno transform"):
        executar_validacao(settings_staging)


def test_relatorio_e_persistido(camada_raw: Settings):
    executar_staging(camada_raw)
    relatorio = executar_validacao(camada_raw)

    caminho = camada_raw.staging_dir / "_validacao" / f"{SNAPSHOT}.json"
    assert caminho.is_file()

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["passou"] is True
    assert dados["snapshot_id"] == SNAPSHOT
    assert len(dados["regras"]) == len(relatorio.regras)
    assert {r["tabela"] for r in dados["reconciliacao"]} == {
        "obras",
        "areas",
        "cnaes",
        "vinculos",
    }


def test_todas_as_regras_sao_avaliadas(camada_raw: Settings):
    """Nenhuma regra pode ficar de fora por erro de template ou nome."""
    from cno_pipeline.validate.regras import REGRAS

    executar_staging(camada_raw)
    relatorio = executar_validacao(camada_raw)

    assert len(relatorio.regras) == len(REGRAS)
    assert {r.nome for r in relatorio.regras} == {r.nome for r in REGRAS}
