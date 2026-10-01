"""Geocodificação offline a partir do `Código de localização`.

O campo é preenchido à mão e mostra isso. Perfilado nos 3,6 M de registros:

    nulo                                1.469.915   40,8%
    Plus Code completo e válido         1.313.391   36,4%
    completo após limpar aspas/espaço      11.746    0,3%
    curto, tipo `RF8J+VH`                 224.313    6,2%
    lixo                                  563.429   15,6%
    sem `+`                                21.362    0,6%

O lixo inclui `00000000+00` (86.043 vezes) e ~12 mil links do plus.codes
truncados no limite de 11 caracteres do campo. O `isValid` da biblioteca rejeita
os dois casos.

Os códigos curtos são recuperados sem dado externo. Falta a eles a célula de
1°×1°, e a âncora para reconstruí-la é a mediana dos pontos já decodificados do
mesmo município. Isso cobre 226.854 dos 227.074 códigos curtos, e em SC a
cobertura é total.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

from openlocationcode import openlocationcode as olc

log = logging.getLogger(__name__)

# Alfabeto do Open Location Code. Sem 0, 1 e vogais, por isso `00000000+00` é
# inválido sem regra especial.
ALFABETO = "23456789CFGHJMPQRVWX"

# Pré-filtros em SQL, para não trazer o lixo ao Python. Quem valida é o `isValid`.
REGEX_COMPLETO = rf"^[{ALFABETO}]{{8}}\+[{ALFABETO}]{{2,3}}$"

# Só 4 caracteres antes do '+'. Com 5 ou 6 o `recoverNearest` pode escolher o
# bloco de 20° errado (uma obra de Sete Lagoas/MG caiu a 1.206 km da âncora),
# então esses 187 códigos ficam sem geocodificação.
REGEX_CURTO = rf"^[{ALFABETO}]{{4}}\+[{ALFABETO}]{{2,3}}$"

# O campo vem com aspas simples e espaços grudados em 11.746 registros, que
# passam a ser válidos depois da limpeza.
SQL_NORMALIZAR = "upper(trim({coluna}, ' ''\"'))"


def decodificar(codigo: str | None) -> tuple[float, float] | None:
    """Coordenada de um Plus Code completo, ou None se o código não for válido."""
    if not codigo:
        return None
    try:
        if not olc.isValid(codigo) or not olc.isFull(codigo):
            return None
        area = olc.decode(codigo)
    except (ValueError, KeyError, IndexError):
        return None
    return area.latitudeCenter, area.longitudeCenter


def recuperar(
    codigo: str | None, lat_ancora: float | None, lon_ancora: float | None
) -> tuple[float, float] | None:
    """Coordenada de um Plus Code curto, reconstruído a partir da âncora."""
    if not codigo or lat_ancora is None or lon_ancora is None:
        return None
    try:
        if not olc.isValid(codigo) or not olc.isShort(codigo):
            return None
        completo = olc.recoverNearest(codigo, lat_ancora, lon_ancora)
        area = olc.decode(completo)
    except (ValueError, KeyError, IndexError):
        return None
    return area.latitudeCenter, area.longitudeCenter


def decodificar_lote(codigos: Iterable[str]) -> Iterator[tuple[str, float, float]]:
    """Decodifica uma sequência de códigos, omitindo os que não valem."""
    for codigo in codigos:
        par = decodificar(codigo)
        if par is not None:
            yield codigo, par[0], par[1]


def recuperar_lote(
    pendentes: Iterable[tuple[str, str, float, float]],
) -> Iterator[tuple[str, str, float, float, float, float]]:
    """Recupera códigos curtos a partir de `(código, município, lat, lon da âncora)`."""
    for codigo, municipio, lat_ancora, lon_ancora in pendentes:
        par = recuperar(codigo, lat_ancora, lon_ancora)
        if par is not None:
            yield codigo, municipio, par[0], par[1], lat_ancora, lon_ancora
