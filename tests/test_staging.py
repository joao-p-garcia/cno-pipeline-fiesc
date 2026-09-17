"""Testes do tratamento, offline, contra uma camada raw sintética.

O fixture reproduz o formato real por inteiro — as 26 colunas do `cno.csv` com
os nomes originais, incluindo os typos da fonte — porque o SQL de tratamento
referencia esses nomes literalmente. Um fixture simplificado passaria sem
exercitar o contrato de verdade.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from cno_pipeline.config import Settings
from cno_pipeline.extract.manifest import ArquivoExtraido, Manifest, sha256_arquivo
from cno_pipeline.transform.staging import ErroDeStaging, executar_staging

SNAPSHOT = "2026-09-12"

CABECALHO_OBRAS = (
    '"CNO","Código do Pais","Nome do pais","Data de início",'
    '"Data de inicio da responsabilidade","Data de registro","CNO vinculado","CEP",'
    '"NI do responsável","Qualificação do responsavel","Nome","Código do municipio",'
    '"Nome do município","Tipo de logradouro","Logradouro","Número do logradouro",'
    '"Bairro","Estado","Caixa Postal","Complemento","Unidade de medida","Área total",'
    '"Situação","Data da situação","Nome empresarial","Código de localização"\n'
)


def _obra(
    cno: str,
    *,
    uf: str = "SC",
    ni: str = "",
    empresarial: str = "",
    data_inicio: str = "2020-03-15",
    data_situacao: str = "2021-06-01",
    area: str = "412.00",
    unidade: str = "m2",
    situacao: str = "02",
    qualificacao: str = "0070",
    pais: str = "105",
    nome_pais: str = "BRASIL",
    localizacao: str = "58PJ64Q5+JP",
    nome: str = "OBRA DE TESTE",
) -> str:
    return (
        f'{cno},{pais},"{nome_pais}",{data_inicio},{data_inicio},2022-05-17,,88010000,'
        f'{ni},{qualificacao},"{nome}",8105,"FLORIANÓPOLIS","RUA","DAS PALMEIRAS","150",'
        f'"CENTRO","{uf}",,"APTO 3","{unidade}",{area},{situacao},{data_situacao},'
        f'"{empresarial}","{localizacao}"\n'
    )


OBRAS_CSV = CABECALHO_OBRAS + "".join(
    [
        # pessoa física: NI e nome empresarial vazios por definição da Receita
        _obra("010010092278"),
        # pessoa jurídica
        _obra("010010119379", ni="02688984000170", empresarial="CONSTRUTORA X LTDA"),
        # sentinelas de data
        _obra("010010119380", data_inicio="1970-01-01", data_situacao="1970-01-01"),
        _obra("010010119381", data_inicio="1900-01-01", data_situacao="2000-01-01"),
        # área absurda, em m2 -> deve ganhar flag e permanecer
        _obra("010010119382", area="555555555555.55"),
        # área grande mas em km -> não é suspeita
        _obra("010010119383", area="9999999.00", unidade="km"),
        # UF por extenso, recuperável
        _obra("010010119384", uf="SÃO PAULO"),
        # UF lixo, deve virar NULL
        _obra("010010119385", uf="estado"),
        # obra no exterior
        _obra("010010119386", uf="EX", pais="249", nome_pais="ESTADOS UNIDOS"),
        # sem plus code
        _obra("010010119387", localizacao=""),
        # situação encerrada
        _obra("010010119388", situacao="15"),
        # tipografia cp1252 no nome
        _obra("010010119389", nome="OBRA – FASE 2"),
    ]
)

AREAS_CSV = (
    '"CNO","Categoria","Destinação","Tipo de obra","Tipo de Área",'
    '"Tipo de Área Complementar","Metragem"\n'
    '010010092278,"Obra Nova","Residencial unifamiliar","Alvenaria","Principal",,412.00\n'
    # linha idêntica à anterior: duplicata real, deve sumir
    '010010092278,"Obra Nova","Residencial unifamiliar","Alvenaria","Principal",,412.00\n'
    # mesma obra, área complementar legítima: NÃO é duplicata
    '010010092278,"Obra Nova","Residencial unifamiliar","Alvenaria",'
    '"Complementar","Piscina",30.00\n'
    '010010119379,"Reforma","Galpão industrial","Mista","Principal",,5258.21\n'
)

CNAES_CSV = (
    '"CNO","CNAE","Data de registro"\n'
    "010010092278,4120400,2022-05-17\n"
    "010010119379,4399103,2026-06-30\n"
)

VINCULOS_CSV = (
    '"CNO","Data de início","Data de fim","Data de registro",'
    '"Qualificação do contribuinte","NI do responsável"\n'
    "010010092278,1988-08-01,,2022-05-26,0053,02688984000170\n"
    # duplicata exata
    "010010092278,1988-08-01,,2022-05-26,0053,02688984000170\n"
    "010010119379,2025-05-23,2026-01-31,2025-05-23,0110,\n"
)

TOTAIS_CSV = (
    '"Total de obras","Total de cnaes","Total de áreas","Total de vínculos"\n'
    '"00000000012","00000000002","00000000004","00000000003"\n'
)

ARQUIVOS = {
    "cno.csv": OBRAS_CSV,
    "cno_areas.csv": AREAS_CSV,
    "cno_cnaes.csv": CNAES_CSV,
    "cno_vinculos.csv": VINCULOS_CSV,
    "cno_totais.csv": TOTAIS_CSV,
}


@pytest.fixture
def settings_staging(tmp_path: Path) -> Settings:
    return Settings(
        source_url="http://exemplo/cno.zip",
        data_dir=tmp_path / "data",
        connect_timeout=5.0,
        read_timeout=5.0,
        max_tentativas=2,
        backoff_base=0.0,
        chunk_size=1024,
        user_agent="cno-pipeline-test",
        manter_zip=True,
        manter_intermediarios=True,
        duckdb_memory_limit="1GB",
        duckdb_threads=2,
    )


@pytest.fixture
def camada_raw(settings_staging: Settings) -> Settings:
    """Materializa uma camada raw sintética, como `cno extract` deixaria."""
    csv_dir = settings_staging.snapshot_dir(SNAPSHOT) / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    arquivos = []
    for nome, conteudo in ARQUIVOS.items():
        caminho = csv_dir / nome
        caminho.write_bytes(conteudo.encode("cp1252"))
        arquivos.append(
            ArquivoExtraido(
                nome=nome,
                bytes=caminho.stat().st_size,
                sha256=sha256_arquivo(caminho),
            )
        )

    Manifest(
        snapshot_id=SNAPSHOT,
        source_url=settings_staging.source_url,
        etag="etag-teste",
        last_modified="Sat, 12 Sep 2026 04:59:45 GMT",
        content_length=1234,
        sha256_zip="deadbeef",
        baixado_em="2026-09-16T00:00:00+00:00",
        extraido_em="2026-09-16T00:00:00+00:00",
        arquivos=tuple(arquivos),
        totais_controle={
            "cno": 12,
            "cno_cnaes": 2,
            "cno_areas": 4,
            "cno_vinculos": 3,
        },
    ).salvar(settings_staging.manifests_dir)

    return settings_staging


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
    assert "" not in nome


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
