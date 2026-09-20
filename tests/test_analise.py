"""Testes da camada de análise: as consultas compartilhadas e o dashboard.

O que estes testes protegem é uma propriedade de arquitetura, não uma conta: o
notebook e o dashboard leem **as mesmas funções**, e o que elas devolvem tem de
continuar sendo o que a camada curada gravou. Um filtro que se perde aqui não dá
erro em lugar nenhum — dá um número diferente em um dos dois lugares.

Rodam sobre a camada sintética, montada pelas mesmas fixtures das outras etapas.
Nada de rede, nada de dado real.
"""

from __future__ import annotations

import pytest

from analise import dados, estilo, malha
from cno_pipeline.config import Settings
from cno_pipeline.curate import executar_curadoria
from cno_pipeline.transform import executar_staging

from .dados_sinteticos import SNAPSHOT


@pytest.fixture
def curada(camada_raw: Settings) -> dados.Curada:
    executar_staging(camada_raw, snapshot_id=SNAPSHOT)
    executar_curadoria(camada_raw, snapshot_id=SNAPSHOT)
    return dados.abrir(camada_raw.curated_dir)


# ---------------------------------------------------------------------------
# Abertura da camada
# ---------------------------------------------------------------------------


def test_camada_ausente_diz_o_que_rodar(tmp_path):
    """O erro tem de ensinar o próximo comando, não vazar traceback de DuckDB."""
    with pytest.raises(dados.CamadaAusente) as erro:
        dados.abrir(tmp_path / "nao-existe")
    assert "make pipeline" in str(erro.value)


def test_snapshot_vem_do_nome_da_particao(curada: dados.Curada):
    """Sem varrer parquet: o DuckDB 1.5.5 estoura ao agregar coluna de partição."""
    assert curada.snapshot == SNAPSHOT


# ---------------------------------------------------------------------------
# As consultas que o notebook e o app dividem
# ---------------------------------------------------------------------------


def test_decomposicao_de_area_separa_os_dois_filtros(curada: dados.Curada):
    """Os quatro números precisam ser diferentes, e o último tem de ser o menor.

    É o gráfico da seção 3 inteiro: se dois critérios passarem a dar o mesmo
    valor, a demonstração de que *cada filtro resolve metade do problema* deixa
    de existir sem ninguém perceber.
    """
    tabela = dados.decomposicao_area(curada).set_index("criterio")["km2"]
    cru = tabela["SUM(area_total) cru"]
    so_m2 = tabela["só o que está em m²"]
    sem_suspeitas = tabela["sem as áreas implausíveis"]
    publicavel = tabela["m² e sem implausíveis (area_m2)"]

    assert publicavel < so_m2 < cru
    assert publicavel < sem_suspeitas < cru


def test_area_m2_ignora_quilometro(curada: dados.Curada):
    """A obra de 9.999.999 km da camada sintética não pode entrar em `area_m2`."""
    unidades = dados.perfil_unidades(curada).set_index("unidade")
    assert "km" in unidades.index
    publicavel = dados.decomposicao_area(curada).set_index("criterio")["km2"]
    assert publicavel["m² e sem implausíveis (area_m2)"] < 1  # nenhum km² inteiro


def test_responsavel_separa_pf_de_pj(curada: dados.Curada):
    tipos = dados.responsavel(curada).set_index("tipo")["obras"]
    assert set(tipos.index) <= {"PF", "PJ"}
    assert tipos.sum() == curada.valor("SELECT count(*) FROM obras")


def test_perfil_geo_nunca_tem_mais_plausiveis_que_pontos(curada: dados.Curada):
    """Plausível é subconjunto de geocodificado. Inverter isso é o erro clássico."""
    perfil = dados.perfil_geo(curada)
    assert (perfil["plausiveis"] <= perfil["pontos"]).all()


def test_plus_code_no_japao_conta_como_ponto_e_nao_como_plausivel(curada: dados.Curada):
    perfil = dados.perfil_geo(curada).set_index("origem")
    assert perfil.loc["completo", "pontos"] > perfil.loc["completo", "plausiveis"]


def test_filtro_de_uf_reduz_a_contagem(curada: dados.Curada):
    """O `WHERE` compartilhado precisa realmente chegar ao SQL de cada pergunta."""
    total = dados.responsavel(curada)["obras"].sum()
    catarinense = dados.responsavel(curada, uf="SC")["obras"].sum()
    assert 0 < catarinense < total


def test_serie_comparavel_corta_o_passado(curada: dados.Curada):
    completa = dados.municipios(curada)["obras"].sum()
    recente = dados.municipios(curada, comparavel=True)["obras"].sum()
    assert recente < completa


def test_marts_e_tabela_analitica_contam_o_mesmo(curada: dados.Curada):
    """Se divergirem, o dashboard e o notebook passam a contar coisas diferentes.

    Inclui as obras **sem UF** de propósito: a junção com o IBGE é `LEFT JOIN`, e
    município que não casa continua na contagem com os campos do IBGE nulos. Uma
    junção que as descartasse faria o total do painel encolher sem aviso, que é
    exatamente o modo de falha que este teste existe para pegar.
    """
    pelo_mart = dados.municipios(curada)["obras"].sum()
    pela_analitica = curada.valor("SELECT count(*) FROM obras")
    assert pelo_mart == pela_analitica


def test_volumetria_conta_obras_e_as_linhas_filhas(curada: dados.Curada):
    """Uma linha por obra em cima, as linhas 1:N colapsadas embaixo."""
    volumetria = dados.volumetria(curada).set_index("o_que")["quantas"]
    assert volumetria["obras (uma linha por obra)"] == curada.valor("SELECT count(*) FROM obras")
    assert volumetria["áreas declaradas (1:N)"] == curada.valor("SELECT sum(n_areas) FROM obras")


# ---------------------------------------------------------------------------
# A amostra crua versionada
# ---------------------------------------------------------------------------


def test_amostra_bruta_tem_bytes_cp1252():
    """O arquivo existe para provar o encoding: sem esses bytes, ele não prova nada."""
    linhas = dados.amostra_bruta()
    assert any(0x80 <= b <= 0x9F for linha in linhas for b in linha)


def test_cp1252_e_latin1_discordam_na_amostra():
    linhas = dados.amostra_bruta()
    assert dados.decodificar(linhas, "cp1252") != dados.decodificar(linhas, "latin-1")


# ---------------------------------------------------------------------------
# Formatação e malha
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "casas", "esperado"),
    [(3604156, 0, "3.604.156"), (2839.05, 1, "2.839,1"), (135, 0, "135"), (0.5, 2, "0,50")],
)
def test_numero_sai_no_padrao_brasileiro(valor, casas, esperado):
    assert estilo.numero(valor, casas) == esperado


@pytest.mark.skipif(not malha.disponivel(), reason="malha não gerada")
def test_malha_recorta_por_uf():
    santa_catarina = malha.por_prefixo("42")
    assert len(santa_catarina["features"]) == 295


@pytest.mark.skipif(not malha.disponivel(), reason="malha não gerada")
def test_aneis_externos_saem_no_sentido_horario():
    """A convenção do D3, que é o oposto da do RFC 7946.

    Com o sentido do RFC, o Vega desenha o complemento do polígono e o mapa vira
    uma mancha chapada — sem erro nenhum no console.
    """
    for feature in malha.por_prefixo("42")["features"][:50]:
        geometria = feature["geometry"]
        poligonos = (
            [geometria["coordinates"]]
            if geometria["type"] == "Polygon"
            else geometria["coordinates"]
        )
        for poligono in poligonos:
            assert malha._area_assinada(poligono[0]) < 0


@pytest.mark.skipif(not malha.disponivel(), reason="malha não gerada")
def test_enquadramento_centra_santa_catarina():
    (lon, lat), escala = malha.enquadramento(malha.por_prefixo("42"), 700, 420)
    assert -54 < lon < -48
    assert -30 < lat < -25
    assert escala > 1000  # escala mundial é ~150; aqui tem de ser muito maior
