"""Testes da camada de análise: as consultas compartilhadas e o dashboard.

O que estes testes protegem é uma propriedade de arquitetura, não uma conta: o
notebook e o dashboard leem **as mesmas funções**, e o que elas devolvem tem de
continuar sendo o que a camada curada gravou. Um filtro que se perde aqui não dá
erro em lugar nenhum — dá um número diferente em um dos dois lugares.

Rodam sobre a camada sintética, montada pelas mesmas fixtures das outras etapas.
Nada de rede, nada de dado real.
"""

from __future__ import annotations

from pathlib import Path

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


# ---------------------------------------------------------------------------
# A paleta, medida
# ---------------------------------------------------------------------------
#
# Os comentários de `analise/estilo.py` afirmam contrastes e separações. Aqui
# eles viram asserção: uma cor trocada "porque ficou mais bonita" que quebre
# alguma dessas contas para o teste, em vez de chegar à apresentação como um
# rótulo que ninguém consegue ler no projetor.


def _canais(cor: str) -> tuple[float, float, float]:
    cor = cor.lstrip("#")
    return tuple(int(cor[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _luminancia(cor: str) -> float:
    def linear(canal: float) -> float:
        return canal / 12.92 if canal <= 0.04045 else ((canal + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _canais(cor))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    """Razão de contraste da WCAG 2.1. 4,5:1 para texto, 3:1 para marca."""
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


def _sobre_o_fundo(cor: str, opacidade: float) -> str:
    """A cor que o olho recebe quando a marca é translúcida sobre a superfície."""
    fundo = _canais(estilo.SUPERFICIE)
    mistura = (
        opacidade * c + (1 - opacidade) * f for c, f in zip(_canais(cor), fundo, strict=True)
    )
    return "#" + "".join(f"{round(c * 255):02x}" for c in mistura)


@pytest.mark.parametrize(
    "papel,cor,minimo",
    [
        ("tinta", estilo.TINTA, 4.5),
        ("tinta secundária", estilo.TINTA_SECUNDARIA, 4.5),
        # Cinza é o "resto" quando um número ganha ênfase. Recuar não é sumir:
        # ele continua sendo uma barra que alguém precisa comparar com a azul.
        ("cinza", estilo.CINZA, 4.5),
        ("azul da série", estilo.AZUL, 3.0),
        ("dourado", estilo.DOURADO, 3.0),
        ("cereja", estilo.CEREJA, 3.0),
        ("azul da marca", estilo.AZUL_MARCA, 3.0),
    ],
)
def test_paleta_tem_contraste_sobre_a_superficie(papel, cor, minimo):
    medido = contraste(cor, estilo.SUPERFICIE)
    assert medido >= minimo, f"{papel} ({cor}) mede {medido:.2f}:1, abaixo de {minimo}:1"


def test_grade_recua_em_vez_de_competir():
    """Limite **superior**, e é de propósito.

    Grade é andaime. Uma grade que passa no contraste de texto está gritando no
    lugar onde o dado deveria falar — o erro oposto ao de sempre, e mais difícil
    de enxergar porque toda régua de acessibilidade elogia contraste alto.
    """
    assert contraste(estilo.GRADE, estilo.SUPERFICIE) <= 3.0


def test_bolha_do_mapa_sobrevive_a_transparencia():
    """A opacidade é o que codifica densidade, e é o que apaga a bolha.

    O número mora em `estilo.OPACIDADE_BOLHA` porque ele não é estético: depende
    do fundo, e o fundo já mudou uma vez.
    """
    vista = _sobre_o_fundo(estilo.AZUL, estilo.OPACIDADE_BOLHA)
    assert contraste(vista, estilo.SUPERFICIE) >= 3.0

    # E duas bolhas empilhadas precisam se distinguir de uma: é o acúmulo que
    # conta a densidade. Sem isto, transparência vira só uma cor mais fraca.
    duas = _sobre_o_fundo(estilo.AZUL, 1 - (1 - estilo.OPACIDADE_BOLHA) ** 2)
    assert _distancia(vista, duas) >= 15


def _simular_daltonismo(cor: str, matriz) -> str:
    """Viénot 1999: projeta a cor no que um dicromata distingue.

    Vale para deuteranopia e protanopia, que juntas respondem pela quase
    totalidade dos casos e são exatamente as que confundem as duas pontas de uma
    paleta quente/fria.
    """

    def linear(canal: float) -> float:
        return canal / 12.92 if canal <= 0.04045 else ((canal + 0.055) / 1.055) ** 2.4

    def gama(canal: float) -> float:
        canal = max(0.0, min(1.0, canal))
        return 12.92 * canal if canal <= 0.0031308 else 1.055 * canal ** (1 / 2.4) - 0.055

    def aplicar(m, v):
        return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]

    para_lms = [
        [0.31399, 0.63951, 0.04650],
        [0.15537, 0.75789, 0.08670],
        [0.01775, 0.10945, 0.87247],
    ]
    de_lms = [
        [5.47221, -4.64196, 0.16963],
        [-1.12524, 2.29317, -0.16789],
        [0.02980, -0.19318, 1.16364],
    ]
    rgb = aplicar(de_lms, aplicar(matriz, aplicar(para_lms, [linear(c) for c in _canais(cor)])))
    return "#" + "".join(f"{round(gama(c) * 255):02x}" for c in rgb)


DEUTERANOPIA = [[1, 0, 0], [0.9513092, 0, 0.04263057], [0, 0, 1]]
PROTANOPIA = [[0, 1.05118294, -0.05116099], [0, 1, 0], [0, 0, 1]]


def _distancia(a: str, b: str) -> float:
    return 100 * sum((x - y) ** 2 for x, y in zip(_canais(a), _canais(b), strict=True)) ** 0.5


@pytest.mark.parametrize("visao", [None, DEUTERANOPIA, PROTANOPIA])
def test_categorias_se_separam_tambem_sob_daltonismo(visao):
    """Cada par do trio categórico, nas três visões.

    O limite de 30 é o que o trio anterior (azul, laranja, verde-água, medido em
    31,5 no pior par) entregava: o tema novo não pode piorar a leitura de quem
    não distingue vermelho de verde só porque ficou mais parecido com a
    identidade do Observatório.
    """
    import itertools

    cores = [c if visao is None else _simular_daltonismo(c, visao) for c in estilo.CATEGORICAS]
    for a, b in itertools.combinations(cores, 2):
        assert _distancia(a, b) >= 30, f"{a} e {b} ficam a {_distancia(a, b):.1f}"


def test_matplotlib_acha_montserrat_nos_dois_pesos():
    """O caderno precisa achar a fonte da marca — e no peso certo.

    Pulado onde o matplotlib não está: ele vive no extra `notebook`, não em
    `dev`, porque o caderno é registro e não serviço. Isso deixa este teste fora
    do CI de propósito, e ele continua valendo justamente onde importa — na
    máquina de quem reexecuta o notebook e commita as figuras.

    O que ele protege é uma falha muda: o Montserrat variável tem instância
    padrão em `wght=100`, e registrá-la direto faria o caderno inteiro sair em
    Thin. Nenhum erro, nenhum aviso — só figuras que ninguém consegue ler no
    projetor.
    """
    pytest.importorskip("matplotlib", reason="extra `notebook` não instalado")
    from matplotlib import font_manager

    estilo.aplicar_matplotlib()

    pesos = {f.weight for f in font_manager.fontManager.ttflist if f.name == estilo.FONTE[0]}
    assert {400, 600} <= pesos, f"Montserrat registrada nos pesos {sorted(pesos)}"

    for peso in ("normal", 600):
        achado = font_manager.findfont(
            font_manager.FontProperties(family=estilo.FONTE, weight=peso)
        )
        assert Path(achado).parent == estilo.DIR_FONTES, (
            f"peso {peso} veio de {achado}, não da fonte versionada — "
            "a figura sairia diferente na máquina de outra pessoa"
        )
