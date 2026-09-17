"""Testes do tratamento, offline, contra uma camada raw sintética.

O fixture reproduz o formato real por inteiro — as 26 colunas do `cno.csv` com
os nomes originais, incluindo os typos da fonte — porque o SQL de tratamento
referencia esses nomes literalmente. Um fixture simplificado passaria sem
exercitar o contrato de verdade.
"""

from __future__ import annotations

import duckdb
import pytest

from cno_pipeline.config import Settings
from cno_pipeline.extract.manifest import ArquivoExtraido, sha256_arquivo
from cno_pipeline.transform.staging import ErroDeStaging, executar_staging

from .dados_sinteticos import OBRAS_CSV, SNAPSHOT


def _consultar(settings: Settings, tabela: str, sql: str):
    caminho = settings.staging_dir / tabela / "**" / "*.parquet"
    return duckdb.connect().sql(sql.format(t=f"read_parquet('{caminho}')")).fetchall()


# -- tipagem -------------------------------------------------------------


def test_tipos_sao_explicitos(camada_raw: Settings):
    executar_staging(camada_raw)
    caminho = camada_raw.staging_dir / "obras" / "**" / "*.parquet"
    tipos = {
        nome: tipo
        for nome, tipo, *_ in duckdb.connect()
        .sql(f"DESCRIBE SELECT * FROM read_parquet('{caminho}')")
        .fetchall()
    }

    assert tipos["cno"] == "VARCHAR"  # zeros à esquerda importam
    assert tipos["cep"] == "VARCHAR"
    assert tipos["data_inicio"] == "DATE"
    assert tipos["area_total"] == "DECIMAL(18,2)"
    assert tipos["obra_ativa"] == "BOOLEAN"


def test_cno_preserva_zeros_a_esquerda(camada_raw: Settings):
    executar_staging(camada_raw)
    (valor,) = _consultar(camada_raw, "obras", "SELECT cno FROM {t} WHERE cno LIKE '01001009%'")[
        0:1
    ][0]
    assert valor == "010010092278"


# -- regras de negócio ---------------------------------------------------


def test_responsavel_tipo_derivado_dos_nulos(camada_raw: Settings):
    """Os nulos de NI não são dados faltantes: são pessoa física."""
    executar_staging(camada_raw)
    resultado = dict(
        _consultar(
            camada_raw,
            "obras",
            "SELECT responsavel_tipo, count(*) FROM {t} GROUP BY 1",
        )
    )
    assert resultado["PJ"] == 1  # só a obra com NI preenchido
    assert resultado["PF"] == 11


def test_sentinelas_de_data_viram_nulo(camada_raw: Settings):
    executar_staging(camada_raw)
    (n_1970, n_1900, nulas) = _consultar(
        camada_raw,
        "obras",
        """SELECT count(*) FILTER (WHERE data_inicio = DATE '1970-01-01'),
                  count(*) FILTER (WHERE data_inicio = DATE '1900-01-01'),
                  count(*) FILTER (WHERE data_inicio IS NULL)
           FROM {t}""",
    )[0]
    assert n_1970 == 0
    assert n_1900 == 0
    assert nulas == 2


def test_situacao_ganha_descricao_legivel(camada_raw: Settings):
    executar_staging(camada_raw)
    resultado = dict(_consultar(camada_raw, "obras", "SELECT situacao_codigo, situacao FROM {t}"))
    assert resultado["02"] == "ATIVA"
    assert resultado["15"] == "ENCERRADA"


def test_uf_por_extenso_e_recuperada_e_lixo_vira_nulo(camada_raw: Settings):
    executar_staging(camada_raw)
    resultado = dict(
        _consultar(
            camada_raw,
            "obras",
            "SELECT uf_origem, uf FROM {t} WHERE uf_origem IN ('SÃO PAULO','estado','EX')",
        )
    )
    assert resultado["SÃO PAULO"] == "SP"
    assert resultado["estado"] is None
    assert resultado["EX"] is None


def test_area_absurda_ganha_flag_mas_nao_e_excluida(camada_raw: Settings):
    """A decisão de descartar é de quem analisa, não do pipeline."""
    executar_staging(camada_raw)
    linhas = _consultar(
        camada_raw,
        "obras",
        "SELECT cno, area_total, area_suspeita FROM {t} WHERE area_suspeita",
    )
    assert len(linhas) == 1
    assert linhas[0][0] == "010010119382"
    assert float(linhas[0][1]) == pytest.approx(555_555_555_555.55)


def test_area_grande_em_outra_unidade_nao_e_suspeita(camada_raw: Settings):
    """9.999.999 km é plausível como ordem de grandeza de via; m² não seria."""
    executar_staging(camada_raw)
    (suspeita,) = _consultar(
        camada_raw, "obras", "SELECT area_suspeita FROM {t} WHERE cno = '010010119383'"
    )[0]
    assert suspeita is False


def test_obra_no_exterior_marcada(camada_raw: Settings):
    executar_staging(camada_raw)
    (n,) = _consultar(camada_raw, "obras", "SELECT count(*) FROM {t} WHERE no_exterior")[0]
    assert n == 1


def test_plus_code_detectado(camada_raw: Settings):
    executar_staging(camada_raw)
    (com, sem) = _consultar(
        camada_raw,
        "obras",
        """SELECT count(*) FILTER (WHERE tem_plus_code),
                  count(*) FILTER (WHERE NOT tem_plus_code) FROM {t}""",
    )[0]
    assert com == 11
    assert sem == 1


def test_tipografia_cp1252_chega_intacta_ao_parquet(camada_raw: Settings):
    executar_staging(camada_raw)
    (nome,) = _consultar(
        camada_raw, "obras", "SELECT nome_obra FROM {t} WHERE cno = '010010119389'"
    )[0]
    assert nome == "OBRA – FASE 2"
    assert "\u0096" not in nome


# -- deduplicação --------------------------------------------------------


def test_duplicatas_exatas_das_filhas_sao_removidas(camada_raw: Settings):
    resultado = executar_staging(camada_raw)

    areas = resultado.tabela("areas")
    assert areas.linhas_origem == 4
    assert areas.linhas_destino == 3  # uma duplicata exata
    assert areas.duplicatas_removidas == 1

    vinculos = resultado.tabela("vinculos")
    assert vinculos.duplicatas_removidas == 1


def test_area_complementar_legitima_nao_e_confundida_com_duplicata(
    camada_raw: Settings,
):
    """Mesma obra com Principal + Complementar são duas linhas válidas."""
    executar_staging(camada_raw)
    (n,) = _consultar(camada_raw, "areas", "SELECT count(*) FROM {t} WHERE cno = '010010092278'")[0]
    assert n == 2


# -- idempotência e robustez ---------------------------------------------


def test_execucao_repetida_produz_o_mesmo_resultado(camada_raw: Settings):
    primeira = executar_staging(camada_raw)
    segunda = executar_staging(camada_raw)

    assert [m.linhas_destino for m in primeira.tabelas] == [
        m.linhas_destino for m in segunda.tabelas
    ]
    # e não duplica arquivos parquet a cada execução
    assert primeira.tabela("obras").arquivos_parquet == (segunda.tabela("obras").arquivos_parquet)


def test_reprocessar_um_snapshot_nao_apaga_outro(camada_raw: Settings):
    executar_staging(camada_raw)

    # materializa um segundo snapshot copiando o primeiro
    outro = "2026-08-01"
    origem = camada_raw.snapshot_dir(SNAPSHOT) / "csv"
    destino = camada_raw.snapshot_dir(outro) / "csv"
    destino.mkdir(parents=True, exist_ok=True)
    for arquivo in origem.iterdir():
        (destino / arquivo.name).write_bytes(arquivo.read_bytes())

    manifesto = camada_raw.manifests_dir / f"{SNAPSHOT}.json"
    (camada_raw.manifests_dir / f"{outro}.json").write_text(
        manifesto.read_text(encoding="utf-8").replace(SNAPSHOT, outro), encoding="utf-8"
    )

    executar_staging(camada_raw, snapshot_id=outro)

    particoes = sorted(p.name for p in (camada_raw.staging_dir / "obras").glob("snapshot_date=*"))
    assert particoes == [f"snapshot_date={outro}", f"snapshot_date={SNAPSHOT}"]


def test_falha_clara_sem_camada_raw(settings_staging: Settings):
    with pytest.raises(ErroDeStaging, match="cno extract"):
        executar_staging(settings_staging)


def test_manifesto_de_staging_registra_metricas(camada_raw: Settings):
    import json

    resultado = executar_staging(camada_raw)
    caminho = camada_raw.staging_dir / "_manifests" / f"{SNAPSHOT}.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))

    assert dados["snapshot_id"] == SNAPSHOT
    # os totais oficiais viajam junto, para a validação reconciliar depois
    assert dados["totais_controle"]["cno"] == 12
    nomes = {t["nome"] for t in dados["tabelas"]}
    assert nomes == {"obras", "areas", "cnaes", "vinculos"}
    assert resultado.segundos_total > 0


# -- transcodificação sob demanda ----------------------------------------


def test_so_transcodifica_arquivos_com_bytes_c1(camada_raw: Settings):
    """Dos cinco arquivos, só o cno.csv tem tipografia cp1252.

    Transcodificar os outros seria trabalho e disco jogados fora: neles latin-1
    e cp1252 produzem exatamente o mesmo texto.
    """
    executar_staging(camada_raw)

    utf8_dir = camada_raw.staging_dir / "_utf8" / f"snapshot_date={SNAPSHOT}"
    transcodificados = {p.name for p in utf8_dir.glob("*.csv")}

    assert transcodificados == {"cno.csv"}


def test_acentos_sobrevivem_na_leitura_direta_em_latin1(camada_raw: Settings):
    """As tabelas lidas sem transcodificar não podem perder acentuação.

    `ã` é 0xE3, que fica na faixa em que latin-1 e cp1252 concordam — é
    justamente por isso que esses arquivos podem ser lidos direto.
    """
    executar_staging(camada_raw)

    destinacoes = {
        d for (d,) in _consultar(camada_raw, "areas", "SELECT DISTINCT destinacao FROM {t}")
    }
    assert "Galpão industrial" in destinacoes

    municipios = {
        m for (m,) in _consultar(camada_raw, "obras", "SELECT DISTINCT nome_municipio FROM {t}")
    }
    assert "FLORIANÓPOLIS" in municipios


def test_arquivo_sem_c1_nao_gera_intermediario(camada_raw: Settings):
    """Se nenhum arquivo precisar, não deve sobrar diretório intermediário."""
    # troca o cno.csv por uma versão sem tipografia cp1252
    csv_dir = camada_raw.snapshot_dir(SNAPSHOT) / "csv"
    sem_c1 = OBRAS_CSV.replace("OBRA – FASE 2", "OBRA FASE 2")
    (csv_dir / "cno.csv").write_bytes(sem_c1.encode("cp1252"))

    # o manifesto precisa refletir o novo sha256
    from cno_pipeline.extract.manifest import carregar_manifest

    manifesto = carregar_manifest(camada_raw.manifests_dir, SNAPSHOT)
    atualizados = tuple(
        ArquivoExtraido(
            nome=a.nome,
            bytes=(csv_dir / a.nome).stat().st_size,
            sha256=sha256_arquivo(csv_dir / a.nome),
        )
        for a in manifesto.arquivos
    )
    from dataclasses import replace

    replace(manifesto, arquivos=atualizados).salvar(camada_raw.manifests_dir)

    executar_staging(camada_raw)

    utf8_dir = camada_raw.staging_dir / "_utf8" / f"snapshot_date={SNAPSHOT}"
    assert not list(utf8_dir.glob("*.csv")) if utf8_dir.exists() else True
