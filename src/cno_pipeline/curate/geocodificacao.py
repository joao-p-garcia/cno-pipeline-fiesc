"""Geocodificação offline a partir do `Código de localização`.

O campo é preenchido à mão e mostra isso. Perfilado nos 3,6 M de registros:

    nulo                                1.469.915   40,8%
    Plus Code completo e válido         1.313.391   36,4%
    completo após limpar aspas/espaço      11.746    0,3%
    curto, tipo `RF8J+VH`                 224.313    6,2%
    lixo                                  563.429   15,6%
    sem `+`                                21.362    0,6%

O lixo conta a história: `00000000+00` aparece 86.043 vezes e há ~12 mil URLs
truncadas no limite de 11 caracteres do campo (`httpsplu+sc`, `httpswww+go`) —
alguém colou link do plus.codes no formulário. Nada disso é recuperável, e o
`isValid` da biblioteca já rejeita os dois casos, então não há filtro artesanal
a manter aqui.

**Os códigos curtos são recuperados sem nenhum dado externo.** Um código curto
omite os 4 caracteres iniciais, que identificam a célula de 1°×1°; para
reconstruí-lo basta uma coordenada de referência a menos de ~0,5° do lugar certo.
Em vez de importar centroides do IBGE, a âncora sai da própria base: a mediana
dos pontos já decodificados do **mesmo município**. Medido, isso cobre 226.854
dos 227.074 códigos curtos — os que sobram estão em municípios sem nenhum código
completo. Em SC a cobertura é total.

A ressalva honesta: município brasileiro mediano cabe folgado em 0,5°, mas alguns
do Amazonas e do Pará não cabem, e lá um ponto pode cair na célula vizinha. Por
isso a curada grava `geo_origem` e a distância até a âncora — quem analisa filtra
ou declara, mas não é enganado em silêncio.

---

**A decodificação roda em Python puro, fora do SQL, e isso é deliberado.**

A primeira versão registrava estas funções como UDF no DuckDB e deixava o SQL
chamá-las por linha. Lia-se melhor e custava caro: cada uma do milhão de linhas
atravessava a fronteira C++↔Python. Medido sobre 1 M de códigos:

    caminho                        local     container
    UDF (SQL chama Python)          17 s        221 s
    Python + CSV + read_csv        5,9 s        6,4 s

O trabalho é idêntico — `olc.decode` custa ~5 µs nos dois ambientes. O que muda
é atravessar a fronteira duas vezes em vez de um milhão. De quebra somem duas
dependências acidentais: `numpy`, que o `create_function` do DuckDB exige, e o
malabarismo de baixar o DuckDB para uma thread só durante a decodificação, que
era preciso para as threads não disputarem o GIL.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

from openlocationcode import openlocationcode as olc

log = logging.getLogger(__name__)

# Alfabeto do Open Location Code. Não inclui 0, 1, A, E, I, O, U e outras letras
# escolhidas justamente para evitar confusão visual e formação de palavras — é o
# que faz `00000000+00` ser inválido sem precisar de regra especial.
ALFABETO = "23456789CFGHJMPQRVWX"

# Pré-filtros em SQL. Servem para não trazer ao Python as 563 mil linhas de lixo;
# a validação de verdade é o `isValid` da biblioteca, dentro das funções.
REGEX_COMPLETO = rf"^[{ALFABETO}]{{8}}\+[{ALFABETO}]{{2,3}}$"

# Exatamente 4 caracteres antes do '+', que é a forma curta padrão e 226.887 dos
# 227.074 casos. Aceitar 5 ou 6 seria aceitar códigos a que falta parte do bloco
# de 20°, e aí o `recoverNearest` escolhe o bloco mais próximo da referência —
# medido, isso pôs uma obra de Sete Lagoas/MG a 1.206 km da âncora. Os 187
# códigos de 5 e 6 caracteres ficam sem geocodificação, que é melhor do que um
# ponto plausível e errado.
REGEX_CURTO = rf"^[{ALFABETO}]{{4}}\+[{ALFABETO}]{{2,3}}$"

# O campo vem com aspas simples e espaços grudados em 11.746 registros, que
# passam a ser válidos depois da limpeza. Barato de recuperar.
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
        # A biblioteca levanta para entrada malformada de formas variadas.
        # Código ilegível é ausência de geocodificação, não falha da etapa.
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
    """Decodifica uma sequência de códigos, omitindo os que não valem.

    Gerador, e não lista, para que a gravação do CSV consuma o resultado à medida
    que ele sai: com 1 M de códigos, materializar tudo antes custaria mais de
    150 MB sem necessidade nenhuma.
    """
    for codigo in codigos:
        par = decodificar(codigo)
        if par is not None:
            yield codigo, par[0], par[1]


def recuperar_lote(
    pendentes: Iterable[tuple[str, str, float, float]],
) -> Iterator[tuple[str, str, float, float, float, float]]:
    """Recupera códigos curtos a partir de `(código, município, lat, lon da âncora)`.

    Devolve a âncora junto com o ponto recuperado porque a camada curada precisa
    dela para medir a distância e decidir se o ponto é plausível.
    """
    for codigo, municipio, lat_ancora, lon_ancora in pendentes:
        par = recuperar(codigo, lat_ancora, lon_ancora)
        if par is not None:
            yield codigo, municipio, par[0], par[1], lat_ancora, lon_ancora
