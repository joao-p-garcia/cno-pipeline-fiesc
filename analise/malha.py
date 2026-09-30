"""Malha municipal do IBGE, para desenhar mapa sem depender de GIS.

Sem geopandas, porque a junção com o CNO é por código de município e não há
operação espacial nenhuma aqui.
"""

from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache

from .referencias import ARQUIVO_MALHA


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

    É o contrário do RFC 7946, mas é a convenção do D3 (e do Vega). No sentido do
    RFC o Altair desenha o planeta inteiro menos o município.
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

    O Vega-Lite não ajusta a projeção sozinho quando a geometria vem inline junto
    com outra camada. O centro é calculado na coordenada Mercator, não na média
    das latitudes.
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

    Cada parte de um `MultiPolygon` vira uma entrada.
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
