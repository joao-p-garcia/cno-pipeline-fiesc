"""SQL da camada curada.

A staging é fiel à origem: quatro tabelas, uma linha por registro publicado. Essa
fidelidade é o que a torna auditável, e é justamente o que a impede de responder
perguntas — "quantos m² Joinville construiu em 2023" exige juntar quatro tabelas e
tomar decisões que a fonte não tomou.

É aqui que essas decisões acontecem, todas explícitas:

* **`area_m2` só existe quando a unidade é m².** A base mistura unidades no mesmo
  campo — 21.328 obras em km, 14.539 em m³, 3.580 em kW, 156.712 em "Outra".
  Somar a coluna crua dá 49.286 km²; somando só o que é metro quadrado dá 2.839.
  Fator de 17 entre o número certo e o errado, e o errado é o que sai de um
  `SUM(area_total)` desavisado.
* **Uma linha por obra.** Áreas e CNAEs são 1:N legítimos e são colapsados, com
  `n_areas` e `n_cnaes` preservados para que a perda de informação seja visível.
* **`serie_comparavel`** marca o que dá para comparar no tempo. Ver `dominios.py`.

Tudo derivado exclusivamente do CNO. População, PIB e malha municipal entram na
camada de análise, nunca aqui — o pipeline reconcilia contra a fonte, e um dado
que a fonte não publica não tem como ser reconciliado.
"""

from __future__ import annotations

from ..transform.schema import AREA_SUSPEITA_M2
from .dominios import (
    DIVISOES_CNAE,
    FAIXAS_AREA_M2,
    LIMITE_PLAUSIBILIDADE_KM,
    PRIMEIRO_ANO_COMPARAVEL,
    SECOES_CNAE,
)
from .geocodificacao import REGEX_COMPLETO, REGEX_CURTO, SQL_NORMALIZAR

# Raio médio da Terra, para a distância até a âncora de geocodificação.
RAIO_TERRA_KM = 6371


def _literal(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


def ler_staging(staging_dir: str, tabela: str, snapshot_id: str) -> str:
    """Lê uma partição de snapshot da staging, recuperando as colunas de partição."""
    caminho = f"{staging_dir}/{tabela}/snapshot_date={snapshot_id}/**/*.parquet"
    return f"read_parquet('{caminho}', hive_partitioning=true)"


def _case_secao_cnae(coluna: str, parte: str) -> str:
    """CASE que mapeia a divisão do CNAE para a letra da seção ou para seu nome."""
    divisao = f"TRY_CAST(substr({coluna}, 1, 2) AS INTEGER)"
    ramos = "\n".join(
        f"        WHEN {divisao} BETWEEN {inicio} AND {fim} "
        f"THEN {_literal(letra if parte == 'letra' else nome)}"
        for inicio, fim, letra, nome in SECOES_CNAE
    )
    return f"CASE\n{ramos}\n        ELSE NULL\n    END"


def _case_divisao_cnae(coluna: str) -> str:
    ramos = "\n".join(
        f"        WHEN {_literal(d)} THEN {_literal(nome)}" for d, nome in DIVISOES_CNAE.items()
    )
    return f"CASE substr({coluna}, 1, 2)\n{ramos}\n        ELSE NULL\n    END"


def _case_faixa_area(coluna: str) -> str:
    ramos = []
    for minimo, maximo, rotulo in FAIXAS_AREA_M2:
        if minimo is None:
            cond = f"{coluna} < {maximo}"
        elif maximo is None:
            cond = f"{coluna} >= {minimo}"
        else:
            cond = f"{coluna} >= {minimo} AND {coluna} < {maximo}"
        ramos.append(f"        WHEN {cond} THEN {_literal(rotulo)}")
    corpo = "\n".join(ramos)
    return f"CASE\n{corpo}\n        ELSE NULL\n    END"


# ---------------------------------------------------------------------------
# Base: obras da staging com o código de localização classificado
# ---------------------------------------------------------------------------


def sql_base(staging_dir: str, snapshot_id: str) -> str:
    """Obras da staging, com o Plus Code normalizado e classificado por forma.

    A classificação por regex é pré-filtro de desempenho, não validação: evita
    chamar a UDF de decodificação nas 563 mil linhas de lixo. Quem decide se o
    código vale é o `isValid` da biblioteca, dentro da função.
    """
    obras = ler_staging(staging_dir, "obras", snapshot_id)
    norm = SQL_NORMALIZAR.format(coluna="codigo_localizacao")
    forma = f"""CASE
        WHEN regexp_matches({norm}, {_literal(REGEX_COMPLETO)}) THEN 'completo'
        WHEN regexp_matches({norm}, {_literal(REGEX_CURTO)})    THEN 'curto'
        ELSE NULL
    END"""
    return f"""
SELECT
    *,
    {norm} AS codigo_norm,
    {forma} AS forma_plus_code,
    -- Chaves de junção já discriminadas por forma. Poderiam ser uma só, com a
    -- forma testada no ON do LEFT JOIN — mas uma condição que olha só o lado
    -- esquerdo dentro do ON impede o planejador de usar hash join e o degrada
    -- para laço aninhado sobre 3,6 M × 1,3 M linhas. Medido: a consulta passava
    -- de dez minutos e não terminava. Com a chave nula onde a forma não bate, o
    -- equi-join puro descarta as linhas sozinho e roda em segundos.
    CASE WHEN {forma} = 'completo' THEN {norm} END AS codigo_completo,
    CASE WHEN {forma} = 'curto'    THEN {norm} END AS codigo_curto
FROM {obras}
"""


# ---------------------------------------------------------------------------
# Geocodificação, em três passos
# ---------------------------------------------------------------------------

SQL_GEO_COMPLETO = """
CREATE OR REPLACE TEMP TABLE geo_completo AS
SELECT * FROM (
    SELECT codigo_norm, olc_lat(codigo_norm) AS latitude, olc_lon(codigo_norm) AS longitude
    FROM (SELECT DISTINCT codigo_norm FROM base WHERE forma_plus_code = 'completo')
) WHERE latitude IS NOT NULL
"""

# A âncora é a mediana dos pontos já decodificados do mesmo município. Mediana e
# não média: um único ponto mal digitado do outro lado do país arrastaria a média
# para fora da célula certa e estragaria a recuperação do município inteiro.
SQL_ANCORAS = """
CREATE OR REPLACE TEMP TABLE ancoras AS
SELECT
    b.codigo_municipio,
    median(g.latitude)  AS lat_ancora,
    median(g.longitude) AS lon_ancora,
    count(*)            AS pontos_ancora
FROM base b
JOIN geo_completo g USING (codigo_norm)
WHERE b.codigo_municipio IS NOT NULL
GROUP BY 1
"""

SQL_GEO_CURTO = """
CREATE OR REPLACE TEMP TABLE geo_curto AS
SELECT * FROM (
    SELECT
        d.codigo_norm,
        d.codigo_municipio,
        olc_lat_curto(d.codigo_norm, a.lat_ancora, a.lon_ancora) AS latitude,
        olc_lon_curto(d.codigo_norm, a.lat_ancora, a.lon_ancora) AS longitude,
        a.lat_ancora,
        a.lon_ancora
    FROM (
        SELECT DISTINCT codigo_norm, codigo_municipio
        FROM base WHERE forma_plus_code = 'curto' AND codigo_municipio IS NOT NULL
    ) d
    JOIN ancoras a USING (codigo_municipio)
) WHERE latitude IS NOT NULL
"""


def _distancia_km(lat: str, lon: str, lat_ref: str, lon_ref: str) -> str:
    """Haversine. Só é calculada para os códigos curtos recuperados."""
    return f"""
    2 * {RAIO_TERRA_KM} * asin(sqrt(
        pow(sin(radians({lat} - {lat_ref}) / 2), 2)
        + cos(radians({lat_ref})) * cos(radians({lat}))
        * pow(sin(radians({lon} - {lon_ref}) / 2), 2)
    ))"""


# ---------------------------------------------------------------------------
# Tabela analítica: uma linha por obra
# ---------------------------------------------------------------------------


def sql_obras_analitico(staging_dir: str, snapshot_id: str) -> str:
    areas = ler_staging(staging_dir, "areas", snapshot_id)
    cnaes = ler_staging(staging_dir, "cnaes", snapshot_id)
    vinculos = ler_staging(staging_dir, "vinculos", snapshot_id)

    area_m2 = "CASE WHEN b.unidade_medida = 'm2' AND NOT b.area_suspeita THEN b.area_total END"
    # A distância é medida contra a mediana do município, para todo ponto
    # geocodificado e não só para os recuperados: um Plus Code completo pode ser
    # válido e ainda assim apontar para o Japão, e 3,7% deles apontam.
    distancia = _distancia_km(
        "coalesce(g.latitude, gc.latitude)",
        "coalesce(g.longitude, gc.longitude)",
        "a.lat_ancora",
        "a.lon_ancora",
    )

    return f"""
WITH area_agg AS (
    SELECT
        cno,
        count(*)                                                  AS n_areas,
        sum(metragem) FILTER (WHERE area_principal)               AS area_principal_m2,
        sum(metragem) FILTER (WHERE NOT area_principal)           AS area_complementar_m2,
        -- Atributos da maior área principal. `arg_max` em vez de `any_value`
        -- porque, havendo várias, a maior é a que descreve a obra.
        arg_max(categoria,   coalesce(metragem, 0)) FILTER (WHERE area_principal) AS categoria,
        arg_max(destinacao,  coalesce(metragem, 0)) FILTER (WHERE area_principal) AS destinacao,
        arg_max(tipo_obra,   coalesce(metragem, 0)) FILTER (WHERE area_principal) AS tipo_obra
    FROM {areas}
    GROUP BY 1
),
cnae_ordenado AS (
    -- A fonte não designa um CNAE principal: a obra tem de um a doze, sem ordem
    -- declarada. Adotamos o primeiro registrado, desempatando pelo código para
    -- que o resultado seja determinístico entre execuções — sem o desempate, duas
    -- rodadas sobre o mesmo dado poderiam escolher CNAEs diferentes.
    SELECT
        cno,
        cnae,
        row_number() OVER (PARTITION BY cno ORDER BY data_registro NULLS LAST, cnae) AS ordem
    FROM {cnaes}
),
cnae_agg AS (
    SELECT
        cno,
        count(*) AS n_cnaes,
        -- `n_cnaes` fica ao lado do escolhido para que o colapso seja auditável:
        -- ele afeta 6,3% das obras, as outras 93,7% têm um CNAE só.
        arg_min(cnae, ordem) AS cnae_principal
    FROM cnae_ordenado
    GROUP BY 1
),
vinculo_agg AS (
    SELECT cno, count(*) AS n_vinculos FROM {vinculos} GROUP BY 1
),
juntado AS (
    SELECT
        b.cno,
        b.snapshot_date,
        b.uf,
        b.codigo_municipio,
        b.nome_municipio,
        -- Fica na tabela para auditoria: sem o código cru não dá para
        -- investigar um ponto que caiu no lugar errado.
        b.codigo_localizacao,
        b.nome_obra,
        b.bairro,
        b.cep,
        b.data_inicio,
        b.data_registro,
        b.data_situacao,
        year(b.data_inicio)                           AS ano_inicio,
        b.situacao_codigo,
        b.situacao,
        b.obra_ativa,
        b.qualificacao_codigo,
        b.qualificacao,
        b.responsavel_tipo,
        b.nome_empresarial,
        b.no_exterior,
        b.uf_indefinida,
        b.datas_incoerentes,

        -- Área: a declarada fica intacta e ao lado da unidade, para ninguém
        -- perder a informação; `area_m2` é a única segura de agregar.
        b.unidade_medida,
        b.area_total                                  AS area_declarada,
        {area_m2}                                     AS area_m2,
        b.area_suspeita,

        coalesce(a.n_areas, 0)                        AS n_areas,
        a.area_principal_m2,
        a.area_complementar_m2,
        a.categoria                                   AS categoria_obra,
        a.destinacao                                  AS destinacao_obra,
        a.tipo_obra,

        coalesce(c.n_cnaes, 0)                        AS n_cnaes,
        c.cnae_principal,
        coalesce(v.n_vinculos, 0)                     AS n_vinculos,

        -- Geocodificação: o completo tem prioridade sobre o recuperado.
        coalesce(g.latitude,  gc.latitude)            AS latitude,
        coalesce(g.longitude, gc.longitude)           AS longitude,
        CASE
            WHEN g.latitude  IS NOT NULL THEN 'completo'
            WHEN gc.latitude IS NOT NULL THEN 'curto_recuperado'
            ELSE NULL
        END                                           AS geo_origem,
        a.pontos_ancora                               AS municipio_pontos_ancora,
        {distancia}                                   AS geo_distancia_municipio_km
    FROM base b
    LEFT JOIN area_agg    a  ON a.cno = b.cno
    LEFT JOIN cnae_agg    c  ON c.cno = b.cno
    LEFT JOIN vinculo_agg v  ON v.cno = b.cno
    LEFT JOIN geo_completo g ON g.codigo_norm = b.codigo_completo
    LEFT JOIN geo_curto   gc ON gc.codigo_norm = b.codigo_curto
                             AND gc.codigo_municipio = b.codigo_municipio
    LEFT JOIN ancoras     a  ON a.codigo_municipio = b.codigo_municipio
)
SELECT
    *,
    {_case_secao_cnae("cnae_principal", "letra")}   AS cnae_secao,
    {_case_secao_cnae("cnae_principal", "nome")}   AS cnae_secao_nome,
    substr(cnae_principal, 1, 2)              AS cnae_divisao,
    {_case_divisao_cnae("cnae_principal")}    AS cnae_divisao_nome,
    {_case_faixa_area("area_m2")}             AS faixa_area,
    (ano_inicio >= {PRIMEIRO_ANO_COMPARAVEL}) AS serie_comparavel,
    (latitude IS NOT NULL)                    AS geocodificada,

    -- Plausibilidade separada da existência do ponto: a coordenada crua fica
    -- gravada para auditoria, e quem plota filtra por esta coluna. Marcar em vez
    -- de apagar é a mesma política de `area_suspeita` na staging.
    coalesce(geo_distancia_municipio_km <= {LIMITE_PLAUSIBILIDADE_KM}, false)
                                              AS geo_plausivel,
    coalesce(area_principal_m2 > {AREA_SUSPEITA_M2}, false) AS area_areas_suspeita
FROM juntado
"""


# ---------------------------------------------------------------------------
# Marts: pequenos e pré-agregados, é o que o dashboard lê
# ---------------------------------------------------------------------------

# O Streamlit não pode varrer 3,6 M de linhas a cada clique num filtro. Estas
# tabelas têm milhares de linhas, respondem instantaneamente e carregam as mesmas
# definições da tabela analítica — o app não recalcula regra de negócio nenhuma,
# que é o que impede o dashboard e o notebook de divergirem.

_MEDIDAS = """
        count(*)                                         AS n_obras,
        count(*) FILTER (WHERE situacao_codigo = '02')    AS n_ativas,
        count(*) FILTER (WHERE situacao_codigo = '15')    AS n_encerradas,
        count(*) FILTER (WHERE situacao_codigo = '14')    AS n_paralisadas,
        count(*) FILTER (WHERE situacao_codigo = '03')    AS n_suspensas,
        count(*) FILTER (WHERE situacao_codigo = '01')    AS n_nulas,
        count(*) FILTER (WHERE responsavel_tipo = 'PJ')   AS n_pj,
        count(area_m2)                                    AS n_com_area_m2,
        sum(area_m2)                                      AS area_m2_total,
        median(area_m2)                                   AS area_m2_mediana,
        -- Só o ponto plausível conta: é este número que legenda o mapa.
        count(*) FILTER (WHERE geo_plausivel)             AS n_geocodificadas"""


def sql_mart_municipio_ano(analitico: str) -> str:
    return f"""
SELECT
    snapshot_date, uf, codigo_municipio, nome_municipio, ano_inicio,
    {_MEDIDAS},
    median(latitude)  FILTER (WHERE geo_plausivel) AS lat_mediana,
    median(longitude) FILTER (WHERE geo_plausivel) AS lon_mediana
FROM {analitico}
GROUP BY 1, 2, 3, 4, 5
"""


def sql_mart_setor_ano(analitico: str) -> str:
    """Recorte setorial pelo CNAE da obra, não pela seção.

    Agrupar por seção daria uma linha só: o CNO é cadastro de obra, e 100% da
    base cai na seção F. O que separa "construção de edifícios" de "obra de
    infraestrutura" é a divisão, e o que separa os tipos de serviço dentro delas
    é a classe — por isso a granularidade aqui é o código completo, com a divisão
    ao lado para agrupar.
    """
    return f"""
SELECT
    snapshot_date, uf, cnae_principal, cnae_divisao,
    any_value(cnae_divisao_nome) AS cnae_divisao_nome, ano_inicio,
    {_MEDIDAS}
FROM {analitico}
GROUP BY 1, 2, 3, 4, 6
"""


def sql_mart_destinacao_ano(analitico: str) -> str:
    return f"""
SELECT
    snapshot_date, uf, destinacao_obra, categoria_obra, faixa_area, ano_inicio,
    {_MEDIDAS}
FROM {analitico}
GROUP BY 1, 2, 3, 4, 5, 6
"""


MARTS = {
    "mart_municipio_ano": sql_mart_municipio_ano,
    "mart_setor_ano": sql_mart_setor_ano,
    "mart_destinacao_ano": sql_mart_destinacao_ano,
}
