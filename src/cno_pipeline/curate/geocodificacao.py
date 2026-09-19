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
dos pontos já decodificados do **mesmo município**. Medido, isso cobre 227.043 dos
227.074 códigos curtos (99,99%) — os 31 restantes estão em 18 municípios que não
têm nenhum código completo, o maior deles com 7 obras. Em SC a cobertura é total.

A ressalva honesta: município brasileiro mediano cabe folgado em 0,5°, mas alguns
do Amazonas e do Pará não cabem, e lá um ponto pode cair na célula vizinha. Por
isso a curada grava `geo_origem` e a distância até a âncora — quem analisa filtra
ou declara, mas não é enganado em silêncio.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from openlocationcode import openlocationcode as olc

log = logging.getLogger(__name__)

# Alfabeto do Open Location Code. Não inclui 0, 1, A, E, I, O, U e outras letras
# escolhidas justamente para evitar confusão visual e formação de palavras — é o
# que faz `00000000+00` ser inválido sem precisar de regra especial.
ALFABETO = "23456789CFGHJMPQRVWX"

# Pré-filtros em SQL. Servem só para não chamar a UDF em 563 mil linhas de lixo;
# a validação de verdade é o `isValid` da biblioteca, dentro da função.
REGEX_COMPLETO = rf"^[{ALFABETO}]{{8}}\+[{ALFABETO}]{{2,3}}$"
# Exatamente 4 caracteres antes do '+', que é a forma curta padrão e 226.887 dos
# 227.074 casos. Aceitar 5 ou 6 seria aceitar códigos a que faltam só um ou dois
# caracteres do bloco de 20°, e aí o `recoverNearest` escolhe o bloco mais
# próximo da referência — medido, isso pôs uma obra de Sete Lagoas/MG a 1.206 km
# da âncora. Os 187 códigos de 5 e 6 caracteres ficam sem geocodificação, que é
# melhor do que um ponto plausível e errado.
REGEX_CURTO = rf"^[{ALFABETO}]{{4}}\+[{ALFABETO}]{{2,3}}$"

# O campo vem com aspas simples e espaços grudados em 11.746 registros, que
# passam a ser válidos depois da limpeza. Barato de recuperar.
SQL_NORMALIZAR = "upper(trim({coluna}, ' ''\"'))"

# Cache pequeno e limitado. O DuckDB avalia uma projeção de cada vez sobre o
# vetor inteiro, então ao pedir latitude e longitude em duas colunas ele chama a
# função duas vezes para as mesmas linhas, em blocos. Um LRU do tamanho de alguns
# vetores transforma a segunda passada em acerto de cache, sem o custo de memória
# de memorizar 1,4 M de códigos distintos.
TAMANHO_CACHE = 8192


@lru_cache(maxsize=TAMANHO_CACHE)
def _decodificar(codigo: str | None) -> tuple[float, float] | None:
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


@lru_cache(maxsize=TAMANHO_CACHE)
def _recuperar(
    codigo: str | None, lat_ref: float | None, lon_ref: float | None
) -> tuple[float, float] | None:
    if not codigo or lat_ref is None or lon_ref is None:
        return None
    try:
        if not olc.isValid(codigo) or not olc.isShort(codigo):
            return None
        completo = olc.recoverNearest(codigo, lat_ref, lon_ref)
        area = olc.decode(completo)
    except (ValueError, KeyError, IndexError):
        return None
    return area.latitudeCenter, area.longitudeCenter


def latitude_de(codigo: str | None) -> float | None:
    par = _decodificar(codigo)
    return par[0] if par else None


def longitude_de(codigo: str | None) -> float | None:
    par = _decodificar(codigo)
    return par[1] if par else None


def latitude_recuperada(codigo: str | None, lat: float | None, lon: float | None) -> float | None:
    par = _recuperar(codigo, lat, lon)
    return par[0] if par else None


def longitude_recuperada(codigo: str | None, lat: float | None, lon: float | None) -> float | None:
    par = _recuperar(codigo, lat, lon)
    return par[1] if par else None


def registrar_udfs(con) -> None:
    """Registra as funções de decodificação na conexão DuckDB.

    Funções separadas para latitude e longitude, em vez de uma que devolva um
    STRUCT, porque o tipo de retorno escalar é trivialmente portável entre versões
    do DuckDB. O custo de chamar duas vezes é absorvido pelo cache.

    `null_handling="special"` é obrigatório aqui. No modo padrão o DuckDB assume
    que a função nunca devolve NULL e aborta a consulta quando devolve — mas
    "este código não é um Plus Code válido" é exatamente um NULL legítimo, e é o
    resultado de 15,6% das linhas. No modo especial a função também passa a
    receber os NULLs de entrada, que ela já trata.
    """
    assinaturas = (
        ("olc_lat", latitude_de, ["VARCHAR"]),
        ("olc_lon", longitude_de, ["VARCHAR"]),
        ("olc_lat_curto", latitude_recuperada, ["VARCHAR", "DOUBLE", "DOUBLE"]),
        ("olc_lon_curto", longitude_recuperada, ["VARCHAR", "DOUBLE", "DOUBLE"]),
    )
    for nome, funcao, parametros in assinaturas:
        con.create_function(nome, funcao, parametros, "DOUBLE", null_handling="special")


def limpar_cache() -> None:
    """Zera os caches. Usado pelos testes, para medir sem interferência."""
    _decodificar.cache_clear()
    _recuperar.cache_clear()
