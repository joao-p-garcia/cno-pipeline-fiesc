"""Construção do SQL de tratamento.

Separado de `staging.py` para que a lógica de negócio — o que cada coluna vira —
possa ser lida e revisada sem o ruído de conexão, arquivos e métricas.

O SQL é montado em Python a partir de `schema.py` em vez de escrito à mão porque
os nomes de coluna da fonte são hostis (`"Qualificação do responsavel"`, com
acento e com o typo original) e repeti-los em texto livre seria fonte garantida
de erro de digitação silencioso.
"""

from __future__ import annotations

from .schema import (
    AREA_SUSPEITA_M2,
    CODIGO_PAIS_BRASIL,
    DATAS_SENTINELA,
    QUALIFICACOES,
    SITUACOES,
    UF_CORRECOES,
    UFS_BRASIL,
    TabelaSpec,
)


def _literal(valor: str) -> str:
    """Escapa um literal de texto para SQL."""
    return "'" + valor.replace("'", "''") + "'"


def _mapa_para_case(coluna: str, mapa: dict[str, str]) -> str:
    """Gera um CASE WHEN a partir de um dicionário de domínio."""
    ramos = "\n".join(f"            WHEN {_literal(k)} THEN {_literal(v)}" for k, v in mapa.items())
    return f"CASE {coluna}\n{ramos}\n            ELSE NULL\n        END"


def texto(coluna_origem: str) -> str:
    """Normaliza texto: apara espaços e trata string vazia como ausente.

    A fonte usa `""` e `"   "` de forma intercambiável com ausência de valor;
    unificar em NULL evita que uma contagem de nulos dependa de qual das duas
    formas o cadastro usou naquele registro.
    """
    return f"nullif(trim(\"{coluna_origem}\"), '')"


def data(coluna_origem: str) -> str:
    """Converte para DATE, neutralizando as sentinelas de "desconhecido"."""
    expr = texto(coluna_origem)
    for sentinela in DATAS_SENTINELA:
        expr = f"nullif({expr}, {_literal(sentinela)})"
    return f"TRY_CAST({expr} AS DATE)"


def numero(coluna_origem: str, tipo: str = "DECIMAL(18,2)") -> str:
    """Converte para número. Valor inconversível vira NULL, não erro de carga."""
    return f"TRY_CAST({texto(coluna_origem)} AS {tipo})"


def flag(expressao: str) -> str:
    """Booleano de dois valores, nunca NULL.

    Em SQL, qualquer comparação com NULL devolve NULL — `NULL LIKE '%+%'` não é
    falso, é desconhecido. Uma flag de três valores é armadilha para quem
    consome: `WHERE NOT tem_plus_code` descartaria em silêncio todas as linhas
    em que a coluna de origem está vazia, que aqui são 40,78% do total.

    Ausência de evidência é tratada como ausência da característica, que é o que
    a flag significa.
    """
    return f"coalesce({expressao}, false)"


# ---------------------------------------------------------------------------
# Tabela principal
# ---------------------------------------------------------------------------


def sql_obras(csv: str, snapshot_id: str) -> str:
    ufs_validas = ", ".join(_literal(uf) for uf in sorted(UFS_BRASIL))
    correcoes_uf = _mapa_para_case('upper(trim("Estado"))', UF_CORRECOES)

    return f"""
WITH limpo AS (
    SELECT
        {texto("CNO")}                                  AS cno,
        {texto("Código do Pais")}                       AS codigo_pais,
        {texto("Nome do pais")}                         AS nome_pais,
        {data("Data de início")}                        AS data_inicio,
        {data("Data de inicio da responsabilidade")}    AS data_inicio_responsabilidade,
        {data("Data de registro")}                      AS data_registro,
        {texto("CNO vinculado")}                        AS cno_vinculado,
        {texto("CEP")}                                  AS cep,
        {texto("NI do responsável")}                    AS ni_responsavel,
        {texto("Qualificação do responsavel")}          AS qualificacao_codigo,
        {texto("Nome")}                                 AS nome_obra,
        {texto("Código do municipio")}                  AS codigo_municipio,
        {texto("Nome do município")}                    AS nome_municipio,
        {texto("Tipo de logradouro")}                   AS tipo_logradouro,
        {texto("Logradouro")}                           AS logradouro,
        {texto("Número do logradouro")}                 AS numero_logradouro,
        {texto("Bairro")}                               AS bairro,
        {texto("Complemento")}                          AS complemento,
        {texto("Unidade de medida")}                    AS unidade_medida,
        {numero("Área total")}                          AS area_total,
        {texto("Situação")}                             AS situacao_codigo,
        {data("Data da situação")}                      AS data_situacao,
        {texto("Nome empresarial")}                     AS nome_empresarial,
        {texto("Código de localização")}                AS codigo_localizacao,

        -- UF: aceita as 27 válidas, recupera as escritas por extenso e
        -- descarta o resto em vez de propagar lixo para o particionamento.
        CASE
            WHEN upper(trim("Estado")) IN ({ufs_validas}) THEN upper(trim("Estado"))
            ELSE {correcoes_uf}
        END                                             AS uf,
        {texto("Estado")}                               AS uf_origem
    FROM read_csv({_literal(csv)}, header = true, all_varchar = true)
),
derivado AS (
    SELECT
        *,
        {_literal(snapshot_id)}                         AS snapshot_date,

        -- Os 66,39% de nulos em ni_responsavel NÃO são dados faltantes: a
        -- Receita deixa o campo em branco quando o responsável é pessoa
        -- física. Virar flag preserva a informação; imputar a destruiria.
        CASE WHEN ni_responsavel IS NULL THEN 'PF' ELSE 'PJ' END
                                                        AS responsavel_tipo,

        {_mapa_para_case("situacao_codigo", SITUACOES)}  AS situacao,
        {_mapa_para_case("qualificacao_codigo", QUALIFICACOES)}
                                                        AS qualificacao,

        -- Ativa = em andamento no cadastro (situação 02).
        {flag("situacao_codigo = '02'")}                 AS obra_ativa,

        codigo_pais IS DISTINCT FROM {_literal(CODIGO_PAIS_BRASIL)}
                                                        AS no_exterior,
        (uf IS NULL)                                    AS uf_indefinida,

        -- Plus Code (Open Location Code) do Google. Presente em 59% dos
        -- registros e decodificável offline, o que abre geolocalização sem
        -- depender de serviço externo pago.
        {flag("codigo_localizacao LIKE '%+%'")}         AS tem_plus_code,

        -- Flag, não exclusão: o maior valor da base é 65x a área do Brasil,
        -- mas quem analisa é que decide o que fazer com o registro.
        {flag(f"unidade_medida = 'm2' AND area_total > {AREA_SUSPEITA_M2}")}
                                                        AS area_suspeita,

        -- Coerência interna: a obra não pode começar depois da data em que a
        -- situação atual foi registrada.
        {
        flag(
            "data_inicio IS NOT NULL AND data_situacao IS NOT NULL AND data_inicio > data_situacao"
        )
    }       AS datas_incoerentes
    FROM limpo
)
SELECT * FROM derivado
QUALIFY row_number() OVER (PARTITION BY cno ORDER BY data_registro DESC NULLS LAST) = 1
"""


# ---------------------------------------------------------------------------
# Tabelas filhas
# ---------------------------------------------------------------------------


def sql_areas(csv: str, snapshot_id: str) -> str:
    return f"""
SELECT DISTINCT
    {texto("CNO")}                          AS cno,
    {texto("Categoria")}                    AS categoria,
    {texto("Destinação")}                   AS destinacao,
    {texto("Tipo de obra")}                 AS tipo_obra,
    {texto("Tipo de Área")}                 AS tipo_area,
    {texto("Tipo de Área Complementar")}    AS tipo_area_complementar,
    {numero("Metragem")}                    AS metragem,
    {flag(texto("Tipo de Área") + " = 'Principal'")} AS area_principal,
    {_literal(snapshot_id)}                 AS snapshot_date
FROM read_csv({_literal(csv)}, header = true, all_varchar = true)
"""


def sql_cnaes(csv: str, snapshot_id: str) -> str:
    return f"""
SELECT DISTINCT
    {texto("CNO")}                  AS cno,
    {texto("CNAE")}                 AS cnae,
    {data("Data de registro")}      AS data_registro,
    {_literal(snapshot_id)}         AS snapshot_date
FROM read_csv({_literal(csv)}, header = true, all_varchar = true)
"""


def sql_vinculos(csv: str, snapshot_id: str) -> str:
    return f"""
SELECT DISTINCT
    {texto("CNO")}                                  AS cno,
    {data("Data de início")}                        AS data_inicio,
    {data("Data de fim")}                           AS data_fim,
    {data("Data de registro")}                      AS data_registro,
    {texto("Qualificação do contribuinte")}         AS qualificacao_codigo,
    {_mapa_para_case(texto("Qualificação do contribuinte"), QUALIFICACOES)}
                                                    AS qualificacao,
    {texto("NI do responsável")}                    AS ni_responsavel,
    ({data("Data de fim")} IS NULL)                 AS vinculo_vigente,
    {_literal(snapshot_id)}                         AS snapshot_date
FROM read_csv({_literal(csv)}, header = true, all_varchar = true)
"""


CONSTRUTORES = {
    "obras": sql_obras,
    "areas": sql_areas,
    "cnaes": sql_cnaes,
    "vinculos": sql_vinculos,
}


def construir(spec: TabelaSpec, csv: str, snapshot_id: str) -> str:
    """Devolve o SELECT de tratamento da tabela."""
    try:
        return CONSTRUTORES[spec.nome](csv, snapshot_id)
    except KeyError as exc:
        raise KeyError(f"sem SQL definido para a tabela {spec.nome!r}") from exc
