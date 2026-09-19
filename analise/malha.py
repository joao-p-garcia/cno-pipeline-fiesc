"""Malha municipal do IBGE, para desenhar mapa sem depender de GIS.

A malha é geometria — não é dado do CNO, e por isso mora aqui, fora do pipeline,
junto com a tabela de municípios. É a mesma fronteira descrita em
`referencias.py`: o que a fonte publica e o pipeline reconcilia fica lá dentro; o
que é conveniência de análise fica aqui.

**Sem geopandas.** Um polígono do GeoJSON é uma lista de pares de coordenadas;
para pintar município por valor não é preciso mais do que isso. Trazer geopandas
custaria GEOS, PROJ e uma cadeia de binários no container, e compraria só o que
`json` já entrega. O preço é não haver operação espacial nenhuma aqui — e não
precisamos de nenhuma: a junção com o CNO é por código de município, não por
geometria.
"""

from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ARQUIVO_MALHA = AQUI / "malha_municipios.geojson.gz"

# O código do IBGE começa com dois dígitos que identificam a UF. É o que permite
# filtrar a malha sem carregar uma segunda tabela de-para.
TAMANHO_PREFIXO_UF = 2


class MalhaAusente(FileNotFoundError):
    """A malha não foi gerada."""

    def __init__(self) -> None:
        super().__init__(
            f"{ARQUIVO_MALHA.name} não existe. Gere com:\n"
            "    python analise/construir_municipios.py"
        )


def disponivel() -> bool:
    """O mapa é opcional: sem a malha, o dashboard mostra tabela e segue."""
    return ARQUIVO_MALHA.is_file()


@lru_cache(maxsize=1)
def carregar() -> dict:
    """Lê a malha inteira, uma vez por processo. São 5.570 polígonos."""
    if not disponivel():
        raise MalhaAusente()
    with gzip.open(ARQUIVO_MALHA, "rt", encoding="utf-8") as arquivo:
        return json.load(arquivo)


@lru_cache(maxsize=32)
def por_prefixo(prefixo: str) -> dict:
    """Recorta a malha pelos primeiros dígitos do código do IBGE.

    Dois dígitos dão uma UF; sete dão um município. Devolve sempre uma
    `FeatureCollection` para que o resultado siga servindo direto ao Altair.
    """
    features = [
        _orientar(feature)
        for feature in carregar()["features"]
        if str(feature["properties"]["codarea"]).startswith(prefixo)
    ]
    return {"type": "FeatureCollection", "features": features}


def _area_assinada(anel: list) -> float:
    """Área pelo método do cadarço. Positiva = anel no sentido anti-horário."""
    return sum(
        atual[0] * seguinte[1] - seguinte[0] * atual[1]
        for atual, seguinte in zip(anel, anel[1:] + anel[:1], strict=True)
    )


def _orientar(feature: dict) -> dict:
    """Põe o anel externo no sentido horário e os buracos no anti-horário.

    **Isto não é purismo de formato, e é o contrário do que o RFC 7946 pede.**
    Quem desenha mapa em projeção esférica — D3, Vega, e portanto o Altair — usa o
    sentido do anel para saber qual lado é o de dentro, e a convenção do D3 é
    **anel externo horário**. Um polígono no sentido "certo" segundo o RFC não
    desenha o município: desenha *o planeta inteiro menos o município*, que na
    tela vira uma mancha chapada cobrindo o gráfico inteiro. Medido nesta malha:
    com o sentido do RFC, 295 municípios viram um retângulo; invertendo, o mapa
    aparece.

    O matplotlib não se importa, porque desenha no plano. Foi por isso que o mapa
    do notebook saiu certo e o do dashboard saiu chapado — o mesmo arquivo, com
    dois desenhistas que discordam sobre o que é dentro.
    """
    geometria = feature["geometry"]
    poligonos = (
        [geometria["coordinates"]] if geometria["type"] == "Polygon" else geometria["coordinates"]
    )
    corrigidos = []
    for poligono in poligonos:
        aneis = []
        for indice, anel in enumerate(poligono):
            externo = indice == 0
            anti_horario = _area_assinada(anel) > 0
            aneis.append(list(reversed(anel)) if anti_horario == externo else anel)
        corrigidos.append(aneis)

    return {
        **feature,
        "geometry": {
            **geometria,
            "coordinates": corrigidos[0] if geometria["type"] == "Polygon" else corrigidos,
        },
    }


def limites(colecao: dict) -> tuple[float, float, float, float]:
    """Caixa envolvente da coleção: (lon_min, lat_min, lon_max, lat_max)."""
    xs = [x for xs, _ in contornos(colecao) for x in xs]
    ys = [y for _, ys in contornos(colecao) for y in ys]
    if not xs:
        raise ValueError("coleção sem geometria")
    return min(xs), min(ys), max(xs), max(ys)


def enquadramento(
    colecao: dict, largura: int, altura: int, margem: float = 0.05
) -> tuple[tuple[float, float], float]:
    """Centro e escala de uma projeção Mercator que faz a coleção caber na tela.

    O Vega-Lite **não** ajusta a projeção sozinho quando a geometria vem inline
    junto com outra camada: o mapa sai desenhado em escala mundial, o estado vira
    um ponto no meio do quadro e ninguém vê erro nenhum. Calcular o enquadramento
    aqui resolve — e é aritmética de Mercator, não dependência de GIS.

    A latitude não é linear em Mercator: `ln(tan(π/4 + φ/2))` é a coordenada
    vertical de verdade, e é nela que o centro precisa ser calculado. Usar a média
    das latitudes desloca o mapa, pouco perto do equador e muito longe dele.
    """
    lon_min, lat_min, lon_max, lat_max = limites(colecao)

    def y_mercator(graus: float) -> float:
        return math.log(math.tan(math.pi / 4 + math.radians(graus) / 2))

    span_lon = math.radians(lon_max - lon_min)
    span_lat = y_mercator(lat_max) - y_mercator(lat_min)
    escala = min(largura / span_lon, altura / span_lat) * (1 - margem)

    centro_lon = (lon_min + lon_max) / 2
    centro_y = (y_mercator(lat_min) + y_mercator(lat_max)) / 2
    centro_lat = math.degrees(2 * math.atan(math.exp(centro_y)) - math.pi / 2)
    return (centro_lon, centro_lat), escala


def contornos(colecao: dict) -> list[tuple[list[float], list[float]]]:
    """Achata os polígonos em listas de x e y, prontas para `plot` ou `fill`.

    Um `MultiPolygon` (ilha, ou município partido por divisa de água) vira várias
    entradas — desenhar a primeira e ignorar o resto apagaria pedaço de mapa.
    """
    caminhos: list[tuple[list[float], list[float]]] = []
    for feature in colecao["features"]:
        geometria = feature["geometry"]
        partes = (
            geometria["coordinates"]
            if geometria["type"] == "Polygon"
            else [anel for poligono in geometria["coordinates"] for anel in poligono]
        )
        for anel in partes:
            if not anel:
                continue
            caminhos.append(([ponto[0] for ponto in anel], [ponto[1] for ponto in anel]))
    return caminhos
