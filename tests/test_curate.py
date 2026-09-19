"""Testes da camada curada.

Dois níveis. Os de unidade cobrem as duas decisões que não são SQL — a seção do
CNAE e a geocodificação —, e os de integração rodam a etapa inteira sobre a
camada sintética, conferindo o que o SQL promete: uma linha por obra, área
agregável só quando a unidade é metro quadrado, e marts que somam o mesmo que a
tabela analítica.

A propriedade mais importante testada aqui é a de que `obras_analitico` tem
exatamente uma linha por obra. Ela junta quatro tabelas, duas delas 1:N, e um
erro de cardinalidade numa junção não dá erro nenhum — só infla silenciosamente
toda contagem a jusante.
"""

from __future__ import annotations

import duckdb
import pytest

from cno_pipeline.config import Settings
from cno_pipeline.curate import ErroDeCuradoria, executar_curadoria, secao_cnae
from cno_pipeline.curate import geocodificacao as geo
from cno_pipeline.curate.dominios import divisao_cnae
from cno_pipeline.transform import executar_staging

from .dados_sinteticos import SNAPSHOT

# ---------------------------------------------------------------------------
# Seção do CNAE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("4120400", ("F", "Construção")),
        ("4399103", ("F", "Construção")),
        ("0111301", ("A", "Agricultura, pecuária, produção florestal, pesca e aquicultura")),
        ("3511501", ("D", "Eletricidade e gás")),
        ("8610101", ("Q", "Saúde humana e serviços sociais")),
        ("9900800", ("U", "Organismos internacionais e outras instituições extraterritoriais")),
    ],
)
def test_secao_cnae_mapeia_divisao(codigo, esperado):
    assert secao_cnae(codigo) == esperado


@pytest.mark.parametrize("codigo", [None, "", "x", "4", "0400000", "9800000"])
def test_secao_cnae_devolve_none_para_codigo_invalido(codigo):
    """Divisões 04, 34, 40, 44, 48, 54, 57, 67, 76, 83, 89 e 98 não existem na CNAE."""
    assert secao_cnae(codigo) is None


# ---------------------------------------------------------------------------
# Geocodificação
# ---------------------------------------------------------------------------


def test_decodifica_plus_code_completo():
    lat = geo.latitude_de("584FPC38+X8")
    lon = geo.longitude_de("584FPC38+X8")
    # Curitibanos, SC. Tolerância de um décimo de grau basta para provar que o
    # ponto caiu no lugar certo sem prender o teste à precisão da célula.
    assert lat == pytest.approx(-27.30, abs=0.1)
    assert lon == pytest.approx(-50.58, abs=0.1)


@pytest.mark.parametrize(
    "lixo",
    [
        None,
        "",
        "00000000+00",  # 86.043 ocorrências na base real
        "httpsplu+sc",  # URL truncada no limite de 11 caracteres do campo
        "8P6GXJEx+tr",  # minúsculas fora do alfabeto OLC
        "3164704",  # código de município no campo errado
        "URBANO",
    ],
)
def test_lixo_nao_vira_coordenada(lixo):
    """Nada disso é recuperável, e nada disso pode virar um ponto no mapa."""
    assert geo.latitude_de(lixo) is None
    assert geo.longitude_de(lixo) is None


def test_codigo_curto_e_recuperado_pela_ancora():
    """`RF8J+VH` só vira coordenada com uma referência a menos de ~0,5°."""
    lat = geo.latitude_recuperada("RF8J+VH", -27.17, -51.50)
    lon = geo.longitude_recuperada("RF8J+VH", -27.17, -51.50)
    assert lat == pytest.approx(-27.18, abs=0.1)
    assert lon == pytest.approx(-51.52, abs=0.1)


def test_codigo_curto_sem_ancora_nao_e_chutado():
    assert geo.latitude_recuperada("RF8J+VH", None, None) is None


def test_codigo_completo_nao_e_tratado_como_curto():
    """As duas funções são excludentes: cada forma tem seu caminho."""
    assert geo.latitude_recuperada("584FPC38+X8", -27.17, -51.50) is None
    assert geo.latitude_de("RF8J+VH") is None


# ---------------------------------------------------------------------------
# Etapa completa, sobre a camada sintética
# ---------------------------------------------------------------------------


@pytest.fixture
def curado(camada_raw: Settings) -> Settings:
    executar_staging(camada_raw, snapshot_id=SNAPSHOT)
    executar_curadoria(camada_raw, snapshot_id=SNAPSHOT)
    return camada_raw


def _consultar(settings: Settings, tabela: str, sql: str):
    caminho = settings.curated_dir / tabela / f"snapshot_date={SNAPSHOT}" / "**" / "*.parquet"
    fonte = f"read_parquet('{str(caminho).replace(chr(92), '/')}', hive_partitioning=true)"
    return duckdb.connect().execute(sql.format(t=fonte)).fetchall()


def test_uma_linha_por_obra(curado: Settings):
    """A junção com áreas e CNAEs não pode multiplicar obra.

    A camada sintética tem obras com três áreas e com duas, exatamente para que
    um erro de cardinalidade apareça aqui em vez de na produção.
    """
    ((total,),) = _consultar(curado, "obras_analitico", "SELECT count(*) FROM {t}")
    ((distintos,),) = _consultar(curado, "obras_analitico", "SELECT count(DISTINCT cno) FROM {t}")
    assert total == distintos == 12


def test_area_m2_ignora_unidades_que_nao_sao_metro_quadrado(curado: Settings):
    """A obra em km tem área declarada, mas não pode entrar numa soma de m²."""
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT unidade_medida, area_declarada, area_m2 FROM {t} WHERE unidade_medida = 'km'",
    )
    assert linhas, "a camada sintética precisa ter uma obra em km"
    for unidade, declarada, area_m2 in linhas:
        assert unidade == "km"
        assert declarada is not None
        assert area_m2 is None


def test_area_suspeita_fica_fora_da_coluna_agregavel(curado: Settings):
    """Quarentena, não exclusão: a obra continua na tabela, a área sai do m²."""
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT area_declarada, area_m2 FROM {t} WHERE area_suspeita",
    )
    assert linhas, "a camada sintética precisa ter uma área implausível"
    for declarada, area_m2 in linhas:
        assert declarada is not None
        assert area_m2 is None


def test_cardinalidade_das_filhas_fica_registrada(curado: Settings):
    """`n_areas` preserva o que o colapso descartou."""
    ((n_areas,),) = _consultar(
        curado,
        "obras_analitico",
        "SELECT n_areas FROM {t} WHERE cno = '010010092278'",
    )
    # Três linhas no CSV, uma delas duplicata exata removida na staging.
    assert n_areas == 2


def test_secao_do_cnae_chega_na_tabela(curado: Settings):
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT DISTINCT cnae_principal, cnae_secao FROM {t} WHERE cnae_principal IS NOT NULL",
    )
    assert linhas
    for codigo, secao in linhas:
        assert secao == secao_cnae(codigo)[0]


def test_geocodificacao_marca_a_origem(curado: Settings):
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT geo_origem, count(*) FROM {t} GROUP BY 1",
    )
    origens = dict(linhas)
    assert origens.get("completo"), "as obras com Plus Code válido precisam ter coordenada"
    # A obra sem código de localização não pode ganhar um ponto inventado.
    assert origens.get(None), "a obra sem Plus Code precisa ficar sem geocodificação"


def test_sem_plus_code_nao_ganha_coordenada(curado: Settings):
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT latitude, longitude, geocodificada FROM {t} WHERE cno = '010010119387'",
    )
    ((lat, lon, geocodificada),) = linhas
    assert lat is None and lon is None and geocodificada is False


def test_codigo_curto_vira_coordenada_pela_ancora_do_municipio(curado: Settings):
    """O caminho que dispensa dado externo: 227 mil códigos da base real."""
    ((origem, lat, lon),) = _consultar(
        curado,
        "obras_analitico",
        "SELECT geo_origem, latitude, longitude FROM {t} WHERE cno = '010010119388'",
    )
    assert origem == "curto_recuperado"
    # Tem de cair no mesmo lugar do código completo dos vizinhos, não em outro
    # bloco de 1° que por acaso também case com a forma curta.
    assert lat == pytest.approx(-15.76, abs=0.1)
    assert lon == pytest.approx(-47.89, abs=0.1)


def test_plus_code_valido_no_lugar_errado_e_marcado(curado: Settings):
    """Sintaticamente perfeito, geograficamente absurdo: geocodifica e sinaliza.

    Marcar em vez de apagar preserva a auditoria — dá para investigar o código
    cru — e ao mesmo tempo mantém o ponto fora de qualquer mapa ou contagem, que
    é a política que `area_suspeita` já usa na staging.
    """
    ((geocodificada, plausivel, distancia, codigo),) = _consultar(
        curado,
        "obras_analitico",
        "SELECT geocodificada, geo_plausivel, geo_distancia_municipio_km, codigo_localizacao "
        "FROM {t} WHERE cno = '010010119389'",
    )
    assert geocodificada is True
    assert plausivel is False
    assert distancia > 1000
    assert codigo == "8Q4GQRQP+J2"


def test_ponto_no_municipio_certo_e_plausivel(curado: Settings):
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT geo_plausivel FROM {t} WHERE geo_origem = 'completo' AND cno <> '010010119389'",
    )
    assert linhas
    assert all(plausivel for (plausivel,) in linhas)


def test_divisao_do_cnae_chega_na_tabela(curado: Settings):
    """Seção não serve de recorte aqui: 100% da base é seção F."""
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT DISTINCT cnae_divisao, cnae_divisao_nome FROM {t} WHERE cnae_principal IS NOT NULL",
    )
    assert linhas
    for divisao, nome in linhas:
        assert divisao in {"41", "42", "43"}
        assert nome == divisao_cnae(divisao + "00000")[1]


def test_serie_comparavel_corta_em_2019(curado: Settings):
    linhas = _consultar(
        curado,
        "obras_analitico",
        "SELECT ano_inicio, serie_comparavel FROM {t} WHERE ano_inicio IS NOT NULL",
    )
    assert linhas
    for ano, comparavel in linhas:
        assert comparavel == (ano >= 2019)


def test_marts_somam_o_mesmo_que_a_tabela_analitica(curado: Settings):
    """Se um mart divergir da analítica, o dashboard mente e ninguém percebe."""
    ((obras,),) = _consultar(curado, "obras_analitico", "SELECT count(*) FROM {t}")
    ((area,),) = _consultar(curado, "obras_analitico", "SELECT sum(area_m2) FROM {t}")

    for mart in ("mart_municipio_ano", "mart_setor_ano", "mart_destinacao_ano"):
        ((n_obras, area_total),) = _consultar(
            curado, mart, "SELECT sum(n_obras), sum(area_m2_total) FROM {t}"
        )
        assert n_obras == obras, f"{mart} não bate na contagem de obras"
        assert area_total == pytest.approx(area), f"{mart} não bate na soma de m²"


def test_reprocessar_o_mesmo_snapshot_e_idempotente(curado: Settings):
    ((antes,),) = _consultar(curado, "obras_analitico", "SELECT count(*) FROM {t}")
    executar_curadoria(curado, snapshot_id=SNAPSHOT)
    ((depois,),) = _consultar(curado, "obras_analitico", "SELECT count(*) FROM {t}")
    assert antes == depois


def test_sem_camada_tratada_a_etapa_falha_explicitamente(settings_staging: Settings):
    with pytest.raises(ErroDeCuradoria, match="camada tratada"):
        executar_curadoria(settings_staging)
