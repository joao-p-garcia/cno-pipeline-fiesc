"""Acesso à camada curada, compartilhado pelo notebook e pelo dashboard.

Cada pergunta tem uma função só, e não há SQL fora daqui, para o notebook e o
app não divergirem num número. Regra de negócio não mora aqui, as constantes vêm
de `curate.dominios`.

O que depende da distribuição de uma coluna varre `obras_analitico` (3,6 M de
linhas); o resto lê os marts.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import duckdb
import pandas as pd

from cno_pipeline.config import get_settings
from cno_pipeline.curate.dominios import (
    FAIXAS_AREA_M2,
    LIMITE_PLAUSIBILIDADE_KM,
    PRIMEIRO_ANO_COMPARAVEL,
)

from . import referencias

AQUI = Path(__file__).resolve().parent
ARQUIVO_AMOSTRA_BRUTA = AQUI / "amostra_bruta.csv"

# View criada na conexão -> tabela materializada pela etapa de curadoria.
TABELAS = {
    "obras": "obras_analitico",
    "municipio_ano": "mart_municipio_ano",
    "setor_ano": "mart_setor_ano",
    "destinacao_ano": "mart_destinacao_ano",
}

# Reexportados do pipeline, são os mesmos objetos e não cópias.
ANO_SERIE_COMPARAVEL = PRIMEIRO_ANO_COMPARAVEL
LIMITE_PLAUSIVEL_KM = LIMITE_PLAUSIBILIDADE_KM

# Na ordem em que o pipeline define as faixas.
ROTULOS_FAIXA_AREA = tuple(rotulo for _, _, rotulo in FAIXAS_AREA_M2)


class CamadaAusente(FileNotFoundError):
    """A camada curada não foi materializada."""

    def __init__(self, caminho: Path) -> None:
        super().__init__(
            f"camada curada não encontrada em {caminho}.\n"
            "Rode `make pipeline` (ou `cno curate`, se a staging já existe)."
        )


def tem_referencias() -> bool:
    """A tabela do IBGE é opcional: sem ela o app perde o denominador, não o resto."""
    return referencias.ARQUIVO_MUNICIPIOS.is_file()


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Curada:
    """Conexão DuckDB, só de leitura, com as tabelas curadas e a referência do IBGE."""

    con: duckdb.DuckDBPyConnection
    curated_dir: Path

    def df(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).df()

    def valor(self, sql: str):
        """Primeira coluna da primeira linha.

        Público para os testes conferirem os marts com SQL cru. O app não chama
        isto, ele usa as funções nomeadas deste módulo.
        """
        return self.con.execute(sql).fetchone()[0]

    @cached_property
    def snapshot(self) -> str:
        """Data de publicação do snapshot, no formato `AAAA-MM-DD`.

        Lida do nome do diretório, porque `max(snapshot_date)` sobre a coluna de
        partição dispara um erro interno no DuckDB 1.5.5.
        """
        return snapshot_mais_recente(self.curated_dir)


def snapshot_mais_recente(curated_dir: Path) -> str:
    """A data do snapshot, lida do nome do diretório de partição.

    Fora da classe porque o dashboard a consulta sem passar pela conexão em cache,
    que envelheceria junto com o processo.
    """
    particao = curated_dir / TABELAS["municipio_ano"]
    datas = sorted(p.name.split("=", 1)[1] for p in particao.glob("snapshot_date=*"))
    if not datas:
        raise CamadaAusente(particao)
    return datas[-1]


def abrir(curated_dir: Path | None = None, *, threads: int | None = None) -> Curada:
    """Abre a camada curada e registra as views que o resto do módulo usa.

    O caminho vem do `Settings` do pipeline, então `CNO_DATA_DIR` vale para os três
    consumidores. Sem `threads`, o DuckDB usa todos os núcleos.

    Cada view lê só a partição do snapshot mais recente. Na nuvem a curada acumula
    snapshots, e um `**/*.parquet` sem esse filtro somaria todos eles.
    """
    destino = curated_dir or get_settings().curated_dir
    if not destino.is_dir():
        raise CamadaAusente(destino)

    mais_recente = snapshot_mais_recente(destino)

    con = duckdb.connect()
    if threads:
        con.execute(f"SET threads = {threads}")
    for view, tabela in TABELAS.items():
        if not (destino / tabela).is_dir():
            raise CamadaAusente(destino / tabela)
        caminho = str(
            destino / tabela / f"snapshot_date={mais_recente}" / "**" / "*.parquet"
        ).replace("\\", "/")
        con.execute(f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT * FROM read_parquet('{caminho}', hive_partitioning=true)
        """)
    if tem_referencias():
        referencias.registrar(con)
    return Curada(con=con, curated_dir=destino)


def _onde(uf: str | None = None, *, comparavel: bool = False, extra: str = "") -> str:
    """Monta a cláusula WHERE comum a quase toda consulta.

    `comparavel` corta a série em `PRIMEIRO_ANO_COMPARAVEL`. É opcional porque o
    degrau antes do corte também é um achado.
    """
    clausulas = []
    if uf:
        clausulas.append(f"uf = '{uf}'")
    if comparavel:
        clausulas.append(f"ano_inicio >= {ANO_SERIE_COMPARAVEL}")
    if extra:
        clausulas.append(extra)
    return "WHERE " + " AND ".join(clausulas) if clausulas else ""


def _em_linhas(sql_agregados: str, rotulo: str, valor: str) -> str:
    """Transpõe um `SELECT` de N agregados em N linhas, com `UNPIVOT`.

    Uma varredura em vez das N de um `UNION ALL`. A ordem das colunas vira a ordem
    das linhas.
    """
    return f"""
        UNPIVOT ({sql_agregados})
        ON COLUMNS(*)
        INTO NAME {rotulo} VALUE {valor}
    """


# ---------------------------------------------------------------------------
# 1. O dado como chega
# ---------------------------------------------------------------------------


def amostra_bruta() -> list[bytes]:
    """Linhas do `cno.csv` original, em bytes, exatamente como a Receita publica."""
    return ARQUIVO_AMOSTRA_BRUTA.read_bytes().splitlines()


def decodificar(linhas: list[bytes], encoding: str) -> list[str]:
    """Decodifica a amostra crua no encoding pedido, sem levantar erro."""
    return [linha.decode(encoding, errors="replace") for linha in linhas]


def totais_do_cabecalho(curada: Curada, uf: str | None = None) -> dict:
    """Obras e municípios, do mart. É o que o topo de toda página do app mostra."""
    linha = curada.df(f"""
        SELECT sum(n_obras) AS obras, count(DISTINCT codigo_municipio) AS municipios
        FROM municipio_ano
        {_onde(uf)}
    """).iloc[0]
    return {"obras": int(linha["obras"]), "municipios": int(linha["municipios"])}


def volumetria(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """O tamanho de cada coisa, já na camada curada. Uma varredura da analítica."""
    return curada.df(
        _em_linhas(
            f"""
            SELECT
                count(*)                          AS "obras (uma linha por obra)",
                count(DISTINCT codigo_municipio)  AS "municípios distintos",
                count(DISTINCT uf)                AS "UFs",
                sum(n_areas)                      AS "áreas declaradas (1:N)",
                sum(n_cnaes)                      AS "CNAEs declarados (1:N)",
                sum(n_vinculos)                   AS "vínculos (1:N)"
            FROM obras
            {_onde(uf)}
            """,
            rotulo="o_que",
            valor="quantas",
        )
    )


# ---------------------------------------------------------------------------
# 2. Perfilamento
# ---------------------------------------------------------------------------


def perfil_unidades(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Distribuição de `unidade_medida` e o quanto cada unidade soma. Varre a analítica."""
    return curada.df(f"""
        SELECT
            unidade_medida                                      AS unidade,
            count(*)                                            AS obras,
            round(sum(area_declarada) / 1e6, 1)                 AS soma_milhoes,
            round(100.0 * count(*) / sum(count(*)) OVER (), 2)  AS pct_obras
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def decomposicao_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Os quatro valores possíveis para "quantos km² esta base soma".

    As linhas do meio isolam a unidade misturada e a área implausível, a última
    aplica os dois. Uma varredura só.
    """
    return curada.df(
        _em_linhas(
            f"""
            SELECT
                round(sum(area_declarada) / 1e6, 1)
                    AS "SUM(area_total) cru",
                round(sum(area_declarada) FILTER (WHERE NOT area_suspeita) / 1e6, 1)
                    AS "sem as áreas implausíveis",
                round(sum(area_declarada) FILTER (WHERE unidade_medida = 'm2') / 1e6, 1)
                    AS "só o que está em m²",
                round(sum(area_m2) / 1e6, 1)
                    AS "m² e sem implausíveis (area_m2)"
            FROM obras
            {_onde(uf)}
            """,
            rotulo="criterio",
            valor="km2",
        )
    )


def areas_implausiveis(curada: Curada, limite: int = 10) -> pd.DataFrame:
    """As maiores áreas declaradas, que o pipeline marca em vez de excluir."""
    return curada.df(f"""
        SELECT cno, uf, nome_municipio AS municipio, unidade_medida AS unidade,
               area_declarada, destinacao_obra AS destinacao
        FROM obras
        WHERE area_suspeita
        ORDER BY area_declarada DESC
        LIMIT {limite}
    """)


def quantis_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Média, mediana e quantis de `area_m2`. Varre a tabela analítica."""
    return curada.df(f"""
        SELECT
            count(area_m2)                  AS obras_com_area,
            round(avg(area_m2), 1)          AS media,
            quantile_cont(area_m2, 0.25)    AS p25,
            median(area_m2)                 AS mediana,
            quantile_cont(area_m2, 0.75)    AS p75,
            quantile_cont(area_m2, 0.95)    AS p95,
            quantile_cont(area_m2, 0.99)    AS p99
        FROM obras
        {_onde(uf)}
    """)


# A última barra acumula tudo acima do teto. Os rótulos dos gráficos leem daqui.
TETO_HISTOGRAMA_M2 = 1000
LARGURA_FAIXA_HISTOGRAMA_M2 = 20


def histograma_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Histograma de `area_m2`, truncado em `TETO_HISTOGRAMA_M2`."""
    return curada.df(f"""
        SELECT
            least(
                floor(area_m2 / {LARGURA_FAIXA_HISTOGRAMA_M2}) * {LARGURA_FAIXA_HISTOGRAMA_M2},
                {TETO_HISTOGRAMA_M2}
            )        AS faixa_inicio,
            count(*) AS obras
        FROM obras
        {_onde(uf, extra="area_m2 IS NOT NULL AND area_m2 > 0")}
        GROUP BY 1
        ORDER BY 1
    """)


def faixas_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Contagem por faixa de área, do mart, na ordem de `FAIXAS_AREA_M2`."""
    ordem = ", ".join(f"'{rotulo}'" for rotulo in ROTULOS_FAIXA_AREA)
    return curada.df(f"""
        SELECT faixa_area, sum(n_obras) AS obras, sum(area_m2_total) / 1e6 AS area_km2
        FROM destinacao_ano
        {_onde(uf, extra="faixa_area IS NOT NULL")}
        GROUP BY 1
        ORDER BY list_position([{ordem}], faixa_area)
    """)


def cardinalidade(curada: Curada) -> pd.DataFrame:
    """O tamanho do 1:N que `n_areas`, `n_cnaes` e `n_vinculos` preservam."""
    return curada.df(
        _em_linhas(
            """
            SELECT
                count(*) FILTER (WHERE n_areas > 1)    AS "obras com mais de uma área",
                count(*) FILTER (WHERE n_areas = 0)    AS "obras sem nenhuma área",
                count(*) FILTER (WHERE n_cnaes > 1)    AS "obras com mais de um CNAE",
                count(*) FILTER (WHERE n_vinculos > 0) AS "obras com algum vínculo",
                max(n_areas)                           AS "maior número de áreas numa obra"
            FROM obras
            """,
            rotulo="situacao",
            valor="obras",
        )
    )


def responsavel(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """PF x PJ, do mart. `responsavel_tipo` nunca é nulo, então `PF = obras - PJ`."""
    linha = curada.df(f"""
        SELECT sum(n_obras) AS obras, sum(n_pj) AS pj
        FROM municipio_ano
        {_onde(uf)}
    """).iloc[0]
    obras, pj = int(linha["obras"] or 0), int(linha["pj"] or 0)
    tabela = pd.DataFrame({"tipo": ["PF", "PJ"], "obras": [obras - pj, pj]}).sort_values(
        "obras", ascending=False, ignore_index=True
    )
    tabela["pct"] = (100.0 * tabela["obras"] / obras).round(1) if obras else 0.0
    return tabela


def situacao(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Distribuição por situação cadastral. Uma varredura do mart."""
    tabela = curada.df(
        _em_linhas(
            f"""
            SELECT
                sum(n_encerradas) AS "Encerrada",
                sum(n_ativas)     AS "Ativa",
                sum(n_paralisadas) AS "Paralisada",
                sum(n_nulas)      AS "Nula",
                sum(n_suspensas)  AS "Suspensa"
            FROM municipio_ano
            {_onde(uf)}
            """,
            rotulo="situacao",
            valor="obras",
        )
    )
    return tabela.sort_values("obras", ascending=False, ignore_index=True)


# ---------------------------------------------------------------------------
# 3. Geocodificação
# ---------------------------------------------------------------------------

SEM_GEOCODIFICACAO = "sem código utilizável"


def perfil_geo(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Cobertura da geocodificação por origem do ponto, com a plausibilidade ao lado."""
    return curada.df(f"""
        SELECT
            coalesce(geo_origem, '{SEM_GEOCODIFICACAO}') AS origem,
            count(*)                                     AS pontos,
            count(*) FILTER (WHERE geo_plausivel)        AS plausiveis,
            round(median(geo_distancia_municipio_km), 2) AS dist_mediana_km,
            round(max(geo_distancia_municipio_km), 0)    AS dist_maxima_km
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY pontos DESC
    """)


def funil_geocodificacao(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Os três números de "cobertura", do mais generoso ao publicável."""
    tabela = curada.df(
        _em_linhas(
            f"""
            SELECT
                count(*) FILTER (WHERE contains(codigo_localizacao, '+'))
                    AS "contém um '+'",
                count(*) FILTER (WHERE geocodificada)
                    AS "decodifica de fato",
                count(*) FILTER (WHERE geo_plausivel)
                    AS "cai no município certo"
            FROM obras
            {_onde(uf)}
            """,
            rotulo="etapa",
            valor="obras",
        )
    )
    total = total_obras(curada, uf)
    tabela["pct_da_base"] = (100.0 * tabela["obras"] / total).round(1)
    return tabela


def total_obras(curada: Curada, uf: str | None = None) -> int:
    """Quantas obras o recorte tem. Do mart, e é o mesmo total do cabeçalho."""
    return int(curada.valor(f"SELECT sum(n_obras) FROM municipio_ano {_onde(uf)}") or 0)


def distancia_geo(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Quantos pontos caem perto, longe e do outro lado do mundo."""
    return curada.df(f"""
        SELECT
            CASE
                WHEN geo_distancia_municipio_km <= {LIMITE_PLAUSIVEL_KM}
                    THEN 'até {LIMITE_PLAUSIVEL_KM} km (plausível)'
                WHEN geo_distancia_municipio_km <= 500  THEN '{LIMITE_PLAUSIVEL_KM} a 500 km'
                WHEN geo_distancia_municipio_km <= 5000 THEN '500 a 5.000 km'
                ELSE 'mais de 5.000 km'
            END      AS faixa,
            count(*) AS pontos
        FROM obras
        {_onde(uf, extra="geocodificada")}
        GROUP BY 1
        ORDER BY min(geo_distancia_municipio_km)
    """)


def pontos_fora(curada: Curada, limite: int = 10) -> pd.DataFrame:
    """Plus Codes válidos que decodificam para o outro lado do planeta."""
    return curada.df(f"""
        SELECT cno, uf, nome_municipio AS municipio, codigo_localizacao AS plus_code,
               round(latitude, 3) AS latitude, round(longitude, 3) AS longitude,
               round(geo_distancia_municipio_km, 0) AS distancia_km
        FROM obras
        WHERE geocodificada
        ORDER BY geo_distancia_municipio_km DESC
        LIMIT {limite}
    """)


def mapa_municipios(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Um ponto por município, com a mediana das coordenadas plausíveis. Lê o mart."""
    return curada.df(f"""
        SELECT
            uf,
            nome_municipio           AS municipio,
            sum(n_obras)             AS obras,
            sum(n_geocodificadas)    AS geocodificadas,
            sum(area_m2_total) / 1e6 AS area_km2,
            median(lat_mediana)      AS latitude,
            median(lon_mediana)      AS longitude
        FROM municipio_ano
        {_onde(uf, extra="lat_mediana IS NOT NULL")}
        GROUP BY 1, 2
        HAVING sum(n_geocodificadas) > 0
        ORDER BY obras DESC
    """)


def prefixo_ibge(curada: Curada, uf: str) -> str:
    """Os dois dígitos com que o código do IBGE identifica a UF."""
    codigo = curada.valor(f"SELECT min(codigo_ibge)::VARCHAR FROM municipios WHERE uf = '{uf}'")
    return str(codigo)[: referencias.TAMANHO_PREFIXO_UF]


# ---------------------------------------------------------------------------
# 4. Tempo
# ---------------------------------------------------------------------------


def obras_por_ano(
    curada: Curada, uf: str | None = None, desde: int = 1990, ate: int | None = None
) -> pd.DataFrame:
    """Série anual de obras e de área, do mart de municípios. `ate` é aberto por padrão."""
    limite = f"ano_inicio BETWEEN {desde} AND {ate}" if ate else f"ano_inicio >= {desde}"
    return curada.df(f"""
        SELECT
            ano_inicio               AS ano,
            sum(n_obras)             AS obras,
            sum(area_m2_total) / 1e6 AS area_km2,
            sum(n_ativas)            AS ativas
        FROM municipio_ano
        {_onde(uf, extra=limite)}
        GROUP BY 1
        ORDER BY 1
    """)


def entrada_no_cadastro(curada: Curada) -> pd.DataFrame:
    """Quando as obras entraram no CNO, por `data_registro` e não `data_inicio`.

    O registro mais antigo é de 19/11/2018, a semana da IN RFB 1.845, e é o que
    sustenta o corte de 2019.
    """
    return curada.df("""
        SELECT
            year(data_registro) AS ano_registro,
            count(*)            AS obras,
            min(data_registro)  AS primeiro_registro
        FROM obras
        WHERE data_registro IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)


def registro_de_obras_antigas(curada: Curada) -> pd.DataFrame:
    """Em que ano entraram as obras que começaram antes do corte."""
    return curada.df(f"""
        SELECT
            year(data_registro) AS ano_registro,
            count(*)            AS obras_iniciadas_antes_de_{ANO_SERIE_COMPARAVEL}
        FROM obras
        WHERE ano_inicio < {ANO_SERIE_COMPARAVEL} AND data_registro IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)


def atraso_de_registro(curada: Curada) -> pd.DataFrame:
    """Quanto tempo separa o início declarado da obra da sua entrada no cadastro."""
    return curada.df(
        _em_linhas(
            """
            SELECT
                count(*) FILTER (WHERE data_registro < data_inicio)
                    AS "registrada antes de começar",
                count(*) FILTER (WHERE datediff('day', data_inicio, data_registro)
                    BETWEEN 0 AND 30)        AS "registrada em até 30 dias",
                count(*) FILTER (WHERE datediff('day', data_inicio, data_registro)
                    BETWEEN 31 AND 365)      AS "registrada em até um ano",
                count(*) FILTER (WHERE datediff('day', data_inicio, data_registro) > 365)
                    AS "registrada mais de um ano depois"
            FROM obras
            WHERE data_registro IS NOT NULL AND data_inicio IS NOT NULL
            """,
            rotulo="situacao",
            valor="obras",
        )
    )


def datas_ausentes(curada: Curada) -> pd.DataFrame:
    """O que fica de fora da série: data nula e ano anterior a 1990."""
    return curada.df("""
        SELECT
            count(*) FILTER (WHERE data_inicio IS NULL) AS sem_data_inicio,
            count(*) FILTER (WHERE ano_inicio < 1990)   AS antes_de_1990,
            min(data_inicio)                            AS data_mais_antiga,
            max(data_inicio)                            AS data_mais_recente
        FROM obras
    """)


# ---------------------------------------------------------------------------
# 5. Recortes: território e setor
# ---------------------------------------------------------------------------

# Sem a tabela do IBGE as colunas continuam existindo, nulas, e o esquema não muda.
COLUNAS_SEM_REFERENCIA = """
    NULL::VARCHAR AS codigo_ibge,
    nome_municipio AS nome_ibge,
    NULL::VARCHAR AS regiao_imediata,
    NULL::VARCHAR AS regiao_intermediaria,
    NULL::BIGINT  AS populacao,
    NULL::DOUBLE  AS latitude_municipio,
    NULL::DOUBLE  AS longitude_municipio,
    false         AS casou_por_correcao
"""


def ranking_ufs(curada: Curada, comparavel: bool = False) -> pd.DataFrame:
    """Obras e área por UF. Com a referência do IBGE, também por mil habitantes."""
    base = f"""
        SELECT uf, sum(n_obras) AS obras, sum(area_m2_total) / 1e6 AS area_km2
        FROM municipio_ano
        {_onde(comparavel=comparavel, extra="uf IS NOT NULL")}
        GROUP BY 1
    """
    if not tem_referencias():
        return curada.df(f"""
            SELECT *, NULL::BIGINT AS populacao, NULL::DOUBLE AS obras_por_mil_hab
            FROM ({base}) ORDER BY obras DESC
        """)

    return curada.df(f"""
        SELECT b.*, p.populacao,
               round(1000.0 * b.obras / p.populacao, 1) AS obras_por_mil_hab
        FROM ({base}) b
        LEFT JOIN (
            SELECT uf, sum({referencias.coluna_populacao()}) AS populacao
            FROM municipios GROUP BY 1
        ) p USING (uf)
        ORDER BY b.obras DESC
    """)


def municipios(
    curada: Curada,
    uf: str | None = None,
    comparavel: bool = False,
    populacao_minima: int = 0,
) -> pd.DataFrame:
    """Um registro por município, com população e região quando há referência.

    `LEFT JOIN` com o IBGE, então município sem par continua na contagem.
    `populacao_minima` tira municípios pequenos, onde a taxa por habitante é ruído.
    """
    base = f"""
        SELECT
            uf, codigo_municipio, nome_municipio,
            sum(n_obras)          AS obras,
            sum(n_ativas)         AS ativas,
            sum(n_geocodificadas) AS geocodificadas,
            sum(area_m2_total)    AS area_m2
        FROM municipio_ano
        {_onde(uf, comparavel=comparavel)}
        GROUP BY 1, 2, 3
    """
    if tem_referencias():
        juntado = referencias.sql_juntar(f"({base})")
    else:
        juntado = f"SELECT *, {COLUNAS_SEM_REFERENCIA} FROM ({base})"

    return curada.df(f"""
        SELECT *,
               CASE WHEN populacao > 0 THEN round(1000.0 * obras / populacao, 1) END
                   AS obras_por_mil_hab
        FROM ({juntado})
        WHERE coalesce(populacao, 0) >= {populacao_minima}
        ORDER BY obras DESC
    """)


def divisoes_cnae(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """As três divisões da seção F, com obras e metros quadrados lado a lado."""
    return curada.df(f"""
        SELECT
            cnae_divisao                 AS divisao,
            any_value(cnae_divisao_nome) AS nome,
            sum(n_obras)                 AS obras,
            sum(area_m2_total) / 1e6     AS area_km2,
            round(100.0 * sum(n_obras) / sum(sum(n_obras)) OVER (), 1) AS pct_obras,
            round(100.0 * sum(area_m2_total) / sum(sum(area_m2_total)) OVER (), 1) AS pct_area
        FROM setor_ano
        {_onde(uf, extra="cnae_divisao IS NOT NULL")}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def destinacoes(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Para que serve a obra, e de que tamanho ela costuma ser.

    Varre a analítica, porque mediana de medianas do mart não é mediana.
    """
    return curada.df(f"""
        SELECT
            coalesce(destinacao_obra, 'não informada') AS destinacao,
            count(*)                 AS obras,
            sum(area_m2) / 1e6       AS area_km2,
            median(area_m2)          AS area_mediana_m2
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def regioes(curada: Curada, uf: str) -> pd.DataFrame:
    """Agrega por região intermediária do IBGE. Exige a tabela de referência."""
    base = f"""
        SELECT uf, nome_municipio, sum(n_obras) AS obras, sum(area_m2_total) AS area_m2
        FROM municipio_ano {_onde(uf)} GROUP BY 1, 2
    """
    return curada.df(f"""
        SELECT
            regiao_intermediaria                           AS regiao,
            count(*)                                       AS municipios,
            sum(obras)                                     AS obras,
            sum(populacao)                                 AS populacao,
            round(1000.0 * sum(obras) / sum(populacao), 1) AS obras_por_mil_hab,
            sum(area_m2) / 1e6                             AS area_km2
        FROM ({referencias.sql_juntar(f"({base})")})
        WHERE regiao_intermediaria IS NOT NULL
        GROUP BY 1
        ORDER BY obras DESC
    """)


def cobertura_referencias(curada: Curada) -> pd.DataFrame:
    """Quantos municípios do CNO casaram com o IBGE, e por qual caminho."""
    base = "SELECT DISTINCT uf, nome_municipio FROM municipio_ano WHERE uf IS NOT NULL"
    return curada.df(f"""
        SELECT
            count(*)                                    AS municipios_no_cno,
            count(codigo_ibge)                          AS casaram,
            count(*) FILTER (WHERE casou_por_correcao)  AS via_tabela_de_correcao,
            count(*) FILTER (WHERE codigo_ibge IS NULL) AS sem_par_no_ibge
        FROM ({referencias.sql_juntar(f"({base})")})
    """)


def ufs_disponiveis(curada: Curada) -> list[str]:
    """UFs presentes na base, para alimentar o seletor do dashboard."""
    return [
        linha[0]
        for linha in curada.con.execute(
            "SELECT DISTINCT uf FROM municipio_ano WHERE uf IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
