"""Acesso à camada curada, compartilhado pelo notebook e pelo dashboard.

**Por que este módulo existe.** O notebook e o Streamlit respondem às mesmas
perguntas. Se cada um escrevesse o próprio SQL, bastaria um `WHERE` diferente
para os dois divergirem num número — e ninguém perceberia, porque os dois
continuariam rodando. Aqui cada pergunta tem uma função só, com um nome, e as
duas pontas chamam a mesma.

**O que ele não faz.** Regra de negócio nenhuma. `area_m2`, `geo_plausivel`,
`serie_comparavel` e a divisão da CNAE já vêm decididas da camada curada; este
módulo só filtra e agrega o que o pipeline gravou. É a mesma fronteira que faz os
marts existirem: quem publica número não pode redefinir o número.

**O que lê o quê.** As funções de perfilamento varrem `obras_analitico` (3,6 M
linhas, 196 MB) porque a pergunta é sobre a distribuição de uma coluna, e isso
não cabe num agregado. Todo o resto lê os marts, que têm de 11 mil a 133 mil
linhas. A docstring de cada função diz qual dos dois ela toca.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import duckdb
import pandas as pd

from cno_pipeline.config import get_settings

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

# Primeiro ano da série comparável. Repetido aqui, e não importado de
# `curate.dominios`, porque a análise pode querer um corte diferente do que o
# pipeline gravou em `serie_comparavel`: são decisões da mesma família, mas não
# são a mesma decisão. O valor está documentado nos dois lugares.
ANO_SERIE_COMPARAVEL = 2019


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
    """Conexão DuckDB com as tabelas curadas e a referência do IBGE registradas.

    Só de leitura: nada aqui escreve em disco. Instanciar é barato — o DuckDB não
    carrega nada até a primeira consulta, e lê o parquet coluna a coluna.
    """

    con: duckdb.DuckDBPyConnection
    curated_dir: Path

    def df(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).df()

    def valor(self, sql: str):
        """Primeira coluna da primeira linha. Para contagens e totais."""
        return self.con.execute(sql).fetchone()[0]

    @cached_property
    def snapshot(self) -> str:
        """Data de publicação do snapshot, no formato `AAAA-MM-DD`.

        É o que prova que o dashboard olha para uma esteira viva, e não para um
        extrato tirado à mão em algum momento do passado.

        Vem do nome do diretório de partição, não de um `max(snapshot_date)`. O
        motivo é prático e vale registrar: o DuckDB 1.5.5 responde agregado sobre
        coluna de partição pela estatística do arquivo, e nesse caminho ele
        estoura um erro interno (`Attempted to access index 17 within vector of
        size 17`). Ler o nome do diretório não varre nada e não depende de quem
        conserta o bug.
        """
        particao = self.curated_dir / TABELAS["municipio_ano"]
        datas = sorted(p.name.split("=", 1)[1] for p in particao.glob("snapshot_date=*"))
        if not datas:
            raise CamadaAusente(particao)
        return datas[-1]


def abrir(curated_dir: Path | None = None, *, threads: int = 4) -> Curada:
    """Abre a camada curada e registra as views que o resto do módulo usa.

    O caminho vem do `Settings` do pipeline, não de uma variável própria: quem
    define onde os dados moram é quem os escreve. Assim `CNO_DATA_DIR` vale para
    o pipeline, para o notebook e para o dashboard sem ser declarado três vezes.
    """
    destino = curated_dir or get_settings().curated_dir
    if not destino.is_dir():
        raise CamadaAusente(destino)

    con = duckdb.connect()
    con.execute(f"SET threads = {threads}")
    for view, tabela in TABELAS.items():
        if not (destino / tabela).is_dir():
            raise CamadaAusente(destino / tabela)
        caminho = str(destino / tabela / "**" / "*.parquet").replace("\\", "/")
        con.execute(f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT * FROM read_parquet('{caminho}', hive_partitioning=true)
        """)
    if tem_referencias():
        referencias.registrar(con)
    return Curada(con=con, curated_dir=destino)


def _onde(uf: str | None = None, *, comparavel: bool = False, extra: str = "") -> str:
    """Monta a cláusula WHERE comum a quase toda consulta.

    `comparavel` corta a série em 2019, quando a migração da matrícula CEI para o
    CNO termina de inflar o cadastro. Fica opcional em vez de embutido porque o
    salto de 2018-2019 é ele próprio um achado — escondê-lo por padrão apagaria a
    evidência de que a série precisa ser cortada.
    """
    clausulas = []
    if uf:
        clausulas.append(f"uf = '{uf}'")
    if comparavel:
        clausulas.append(f"ano_inicio >= {ANO_SERIE_COMPARAVEL}")
    if extra:
        clausulas.append(extra)
    return "WHERE " + " AND ".join(clausulas) if clausulas else ""


# ---------------------------------------------------------------------------
# 1. O dado como chega
# ---------------------------------------------------------------------------


def amostra_bruta() -> list[bytes]:
    """Linhas do `cno.csv` original, em bytes, exatamente como a Receita publica.

    Ficam em bytes de propósito: é o único jeito de mostrar que a mesma sequência
    decodifica de duas formas diferentes e só uma delas está certa.
    """
    return ARQUIVO_AMOSTRA_BRUTA.read_bytes().splitlines()


def decodificar(linhas: list[bytes], encoding: str) -> list[str]:
    """Decodifica a amostra crua no encoding pedido, sem levantar erro.

    `latin-1` nunca falha — decodifica qualquer byte. É exatamente por isso que
    ele é a escolha perigosa: o erro não aparece na leitura, aparece no relatório.
    """
    return [linha.decode(encoding, errors="replace") for linha in linhas]


def volumetria(curada: Curada) -> pd.DataFrame:
    """O tamanho de cada coisa, já na camada curada."""
    return curada.df("""
        SELECT 'obras (uma linha por obra)' AS o_que, count(*) AS quantas FROM obras
        UNION ALL SELECT 'municípios distintos',        count(DISTINCT codigo_municipio) FROM obras
        UNION ALL SELECT 'UFs',                         count(DISTINCT uf) FROM obras
        UNION ALL SELECT 'áreas declaradas (1:N)',      sum(n_areas) FROM obras
        UNION ALL SELECT 'CNAEs declarados (1:N)',      sum(n_cnaes) FROM obras
        UNION ALL SELECT 'vínculos (1:N)',              sum(n_vinculos) FROM obras
    """)


# ---------------------------------------------------------------------------
# 2. Perfilamento — varre a tabela analítica
# ---------------------------------------------------------------------------


def perfil_unidades(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Distribuição de `unidade_medida` e o quanto cada unidade soma.

    Varre `obras_analitico`. É a consulta que desmonta o `SUM(area_total)`: a
    coluna de área guarda metro quadrado, quilômetro, metro cúbico e quilowatt no
    mesmo lugar, e a soma crua não pergunta.
    """
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

    Cada linha acrescenta um filtro à anterior. A distância entre a primeira e a
    última é o tamanho do erro que um `SUM` desavisado publicaria.
    """
    onde = _onde(uf)
    return curada.df(f"""
        SELECT * FROM (
            SELECT 1 AS ordem, 'SUM(area_total) cru' AS criterio,
                   round(sum(area_declarada) / 1e6, 1) AS km2
            FROM obras {onde}
            UNION ALL
            SELECT 2, 'sem as áreas implausíveis',
                   round(sum(area_declarada) FILTER (WHERE NOT area_suspeita) / 1e6, 1)
            FROM obras {onde}
            UNION ALL
            SELECT 3, 'só o que está em m²',
                   round(sum(area_declarada) FILTER (WHERE unidade_medida = 'm2') / 1e6, 1)
            FROM obras {onde}
            UNION ALL
            SELECT 4, 'm² e sem implausíveis (area_m2)',
                   round(sum(area_m2) / 1e6, 1)
            FROM obras {onde}
        ) ORDER BY ordem
    """)


def areas_implausiveis(curada: Curada, limite: int = 10) -> pd.DataFrame:
    """As maiores áreas declaradas — as que o pipeline marca em vez de excluir."""
    return curada.df(f"""
        SELECT cno, uf, nome_municipio AS municipio, unidade_medida AS unidade,
               area_declarada, destinacao_obra AS destinacao
        FROM obras
        WHERE area_suspeita
        ORDER BY area_declarada DESC
        LIMIT {limite}
    """)


def quantis_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Média, mediana e quantis de `area_m2`. Varre a tabela analítica.

    A média e a mediana no mesmo quadro porque a diferença entre elas é o
    argumento: a média de 834 m² não descreve obra nenhuma.
    """
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


def histograma_area(curada: Curada, uf: str | None = None, teto: int = 1000) -> pd.DataFrame:
    """Histograma de `area_m2` em faixas de 20 m², truncado no teto.

    O truncamento é declarado no rótulo da última faixa em vez de escondido: a
    cauda some do gráfico, não da contagem.
    """
    return curada.df(f"""
        SELECT
            least(floor(area_m2 / 20) * 20, {teto}) AS faixa_inicio,
            count(*)                                AS obras
        FROM obras
        {_onde(uf, extra="area_m2 IS NOT NULL AND area_m2 > 0")}
        GROUP BY 1
        ORDER BY 1
    """)


def faixas_area(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Contagem por faixa de área, na classificação que o pipeline gravou."""
    return curada.df(f"""
        SELECT faixa_area, sum(n_obras) AS obras, sum(area_m2_total) / 1e6 AS area_km2
        FROM destinacao_ano
        {_onde(uf, extra="faixa_area IS NOT NULL")}
        GROUP BY 1
        ORDER BY min(CASE faixa_area
            WHEN 'até 70 m²'     THEN 1
            WHEN '70 a 150 m²'   THEN 2
            WHEN '150 a 500 m²'  THEN 3
            WHEN '500 a 5.000 m²' THEN 4
            ELSE 5 END)
    """)


def cardinalidade(curada: Curada) -> pd.DataFrame:
    """Quanta informação o colapso para uma linha por obra teve que guardar.

    É o tamanho do 1:N que `n_areas` e `n_cnaes` preservam — e a razão de as duas
    colunas existirem em vez de o colapso ser silencioso.
    """
    return curada.df("""
        SELECT 'obras com mais de uma área' AS situacao, count(*) AS obras
        FROM obras WHERE n_areas > 1
        UNION ALL SELECT 'obras sem nenhuma área',          count(*) FROM obras WHERE n_areas = 0
        UNION ALL SELECT 'obras com mais de um CNAE',       count(*) FROM obras WHERE n_cnaes > 1
        UNION ALL SELECT 'obras com algum vínculo',         count(*) FROM obras WHERE n_vinculos > 0
        UNION ALL SELECT 'maior número de áreas numa obra', max(n_areas) FROM obras
    """)


def responsavel(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """PF x PJ — a coluna que nasceu de um campo nulo em 66% das linhas."""
    return curada.df(f"""
        SELECT responsavel_tipo AS tipo, count(*) AS obras,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY obras DESC
    """)


def situacao(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Distribuição por situação cadastral, a partir do mart de municípios."""
    onde = _onde(uf)
    return curada.df(f"""
        SELECT 'Encerrada' AS situacao, sum(n_encerradas) AS obras FROM municipio_ano {onde}
        UNION ALL SELECT 'Ativa',      sum(n_ativas)      FROM municipio_ano {onde}
        UNION ALL SELECT 'Paralisada', sum(n_paralisadas) FROM municipio_ano {onde}
        UNION ALL SELECT 'Nula',       sum(n_nulas)       FROM municipio_ano {onde}
        UNION ALL SELECT 'Suspensa',   sum(n_suspensas)   FROM municipio_ano {onde}
        ORDER BY obras DESC
    """)


# ---------------------------------------------------------------------------
# 3. Geocodificação
# ---------------------------------------------------------------------------


def perfil_geo(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Cobertura da geocodificação por origem do ponto, com a plausibilidade ao lado.

    As duas colunas juntas são o argumento: `pontos` é a cobertura que um
    relatório otimista citaria, `plausiveis` é a que sobrevive a ser conferida
    contra o município declarado.
    """
    return curada.df(f"""
        SELECT
            coalesce(geo_origem, 'sem código utilizável') AS origem,
            count(*)                                      AS pontos,
            count(*) FILTER (WHERE geo_plausivel)         AS plausiveis,
            round(median(geo_distancia_municipio_km), 2)  AS dist_mediana_km,
            round(max(geo_distancia_municipio_km), 0)     AS dist_maxima_km
        FROM obras
        {_onde(uf)}
        GROUP BY 1
        ORDER BY pontos DESC
    """)


def distancia_geo(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """Quantos pontos caem perto, longe e do outro lado do mundo."""
    return curada.df(f"""
        SELECT
            CASE
                WHEN geo_distancia_municipio_km <= 150  THEN 'até 150 km (plausível)'
                WHEN geo_distancia_municipio_km <= 500  THEN '150 a 500 km'
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
    """Um ponto por município, com a mediana das coordenadas plausíveis.

    Lê o mart, não as 3,6 M de obras: o mapa responde na hora e continua sendo o
    mesmo número que o resto do painel mostra.
    """
    return curada.df(f"""
        SELECT
            uf,
            nome_municipio          AS municipio,
            sum(n_obras)            AS obras,
            sum(n_geocodificadas)   AS geocodificadas,
            sum(area_m2_total) / 1e6 AS area_km2,
            median(lat_mediana)     AS latitude,
            median(lon_mediana)     AS longitude
        FROM municipio_ano
        {_onde(uf, extra="lat_mediana IS NOT NULL")}
        GROUP BY 1, 2
        HAVING sum(n_geocodificadas) > 0
        ORDER BY obras DESC
    """)


# ---------------------------------------------------------------------------
# 4. Tempo
# ---------------------------------------------------------------------------


def obras_por_ano(
    curada: Curada, uf: str | None = None, desde: int = 1990, ate: int = 2026
) -> pd.DataFrame:
    """Série anual de obras e de área, do mart de municípios."""
    return curada.df(f"""
        SELECT
            ano_inicio                  AS ano,
            sum(n_obras)                AS obras,
            sum(area_m2_total) / 1e6    AS area_km2,
            sum(n_ativas)               AS ativas
        FROM municipio_ano
        {_onde(uf, extra=f"ano_inicio BETWEEN {desde} AND {ate}")}
        GROUP BY 1
        ORDER BY 1
    """)


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


def ranking_ufs(curada: Curada, comparavel: bool = False) -> pd.DataFrame:
    """Obras e área por UF. Com a referência do IBGE, também por mil habitantes."""
    base = f"""
        SELECT uf, sum(n_obras) AS obras, sum(area_m2_total) / 1e6 AS area_km2
        FROM municipio_ano
        {_onde(comparavel=comparavel, extra="uf IS NOT NULL")}
        GROUP BY 1
    """
    if not tem_referencias():
        return curada.df(f"SELECT * FROM ({base}) ORDER BY obras DESC")

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


def municipios(curada: Curada, uf: str | None = None, comparavel: bool = False) -> pd.DataFrame:
    """Um registro por município, com população e região quando há referência.

    A junção com o IBGE é a de `referencias.sql_juntar` — a mesma que o notebook
    usa. É `LEFT JOIN`: município que não casa continua na contagem, com o
    denominador nulo, em vez de sumir do total sem aviso.
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
    if not tem_referencias():
        return curada.df(f"SELECT * FROM ({base}) ORDER BY obras DESC")

    return curada.df(f"""
        SELECT *,
               CASE WHEN populacao > 0 THEN round(1000.0 * obras / populacao, 1) END
                   AS obras_por_mil_hab
        FROM ({referencias.sql_juntar(f"({base})")})
        ORDER BY obras DESC
    """)


def divisoes_cnae(curada: Curada, uf: str | None = None) -> pd.DataFrame:
    """As três divisões da seção F, com obras e metros quadrados lado a lado.

    Lado a lado porque é aí que está o achado: infraestrutura é uma fatia pequena
    das obras e uma fatia grande da área.
    """
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


def destinacoes(curada: Curada, uf: str | None = None, limite: int = 10) -> pd.DataFrame:
    """Para que serve a obra, e de que tamanho ela costuma ser.

    Varre a tabela analítica, embora exista um mart com o mesmo recorte. O motivo
    é a mediana: o mart guarda a mediana de cada grupo (UF × destinação × faixa ×
    ano), e **mediana de medianas não é mediana** — somar contagens a partir de um
    agregado é exato, tirar quantil não é. Contagem e área viriam do mart; a
    mediana teria que ser inventada. Um número inventado por conveniência é
    exatamente o que este projeto não publica.
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
        LIMIT {limite}
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
