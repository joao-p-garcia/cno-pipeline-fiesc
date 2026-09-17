"""Contrato de dados da camada staging: nomes, domínios e regras de limpeza.

Este módulo é declarativo de propósito. A mecânica de carga vive em
`staging.py`; aqui fica só *o que* a camada tratada promete, para que a
validação e a análise leiam a mesma definição em vez de repetir regras.

Duas decisões atravessam todo o módulo:

**Tudo é lido como texto e convertido explicitamente.** A fonte é um cadastro
público com preenchimento livre em vários campos, e deixar o `read_csv` inferir
tipos faria a carga falhar num valor ruim isolado — ou, pior, silenciosamente
tratar a coluna inteira como texto sem ninguém perceber. Lendo como `VARCHAR` e
aplicando `TRY_CAST` depois, um valor inconversível vira `NULL` **contabilizado**
em vez de derrubar 3,6 milhões de linhas.

**Nada é descartado por suspeita.** Registros implausíveis recebem flag e
continuam na tabela. Quem analisa decide se exclui; o pipeline não decide por
ele.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Domínios publicados pela Receita (metadados/metadados_cno_geral.csv)
# ---------------------------------------------------------------------------

SITUACOES: dict[str, str] = {
    "01": "NULA",
    "02": "ATIVA",
    "03": "SUSPENSA",
    "14": "PARALISADA",
    "15": "ENCERRADA",
}

QUALIFICACOES: dict[str, str] = {
    "0053": "Pessoa Jurídica Construtora",
    "0057": "Dono da Obra",
    "0064": "Incorporador de Construção Civil",
    "0070": "Proprietário do Imóvel",
    "0109": "Consórcio",
    "0110": "Construção em nome coletivo",
    "0111": "Sociedade Líder de Consórcio",
}

# As 27 unidades federativas. Escrito como string separada por espaço porque a
# lista literal equivalente ocupa 27 linhas ou estoura o limite de coluna, e
# nenhuma das duas formas se lê melhor do que esta.
_UFS = "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO"

UFS_BRASIL: frozenset[str] = frozenset(_UFS.split())

# ---------------------------------------------------------------------------
# Regras de limpeza, derivadas do perfilamento da base
# ---------------------------------------------------------------------------

# Datas que a fonte usa como "desconhecido" em vez de deixar vazio. Mantê-las
# como data real distorceria qualquer série temporal: 556 obras apareceriam
# começando em 1970 e 23 em 1900.
DATAS_SENTINELA: tuple[str, ...] = ("1900-01-01", "1970-01-01", "0001-01-01")

# Área acima da qual o registro é marcado para revisão. O maior valor da base é
# 555.555.555.555 m², cerca de 65 vezes a área do Brasil — claramente digitação.
# O corte é conservador e serve só para sinalizar: como é flag e não exclusão,
# um falso positivo não custa nada, enquanto deixar passar distorce média e
# desvio padrão de qualquer agregação.
AREA_SUSPEITA_M2: int = 1_000_000

# Código do país do Brasil no cadastro.
CODIGO_PAIS_BRASIL: str = "105"

# O campo `Estado` tem 35 valores distintos em vez de 27. A maioria do excedente
# é de obras no exterior ou digitação livre, mas dois casos são a UF correta por
# extenso e dá para recuperar sem ambiguidade. Os demais (`CHILE`, `CHUBUT`,
# `BUENO ARIES`, `estado`, vazio) viram NULL — são menos de dez registros, e
# inventar uma UF para eles seria pior do que admitir que não se sabe.
UF_CORRECOES: dict[str, str] = {
    "SÃO PAULO": "SP",
    "PERNAMBUCO": "PE",
}


@dataclass(frozen=True)
class TabelaSpec:
    """Descreve uma tabela da camada staging."""

    nome: str
    arquivo_origem: str
    # origem -> destino. A ordem define a ordem das colunas no parquet.
    colunas: dict[str, str]
    # Colunas que identificam uma linha, usadas para desduplicar.
    chave_dedup: tuple[str, ...]
    # Colunas de particionamento do parquet.
    particoes: tuple[str, ...] = ()
    # Colunas da origem deliberadamente não propagadas, com o motivo.
    descartadas: dict[str, str] = field(default_factory=dict)

    @property
    def colunas_origem(self) -> tuple[str, ...]:
        return tuple(self.colunas)


# ---------------------------------------------------------------------------
# Tabelas
#
# Os nomes de origem preservam os erros da fonte ("Qualificação do responsavel"
# sem acento no segundo termo, "Data de inicio da responsabilidade"). Eles são
# a chave real do CSV e não podem ser "corrigidos" aqui.
# ---------------------------------------------------------------------------

OBRAS = TabelaSpec(
    nome="obras",
    arquivo_origem="cno.csv",
    colunas={
        "CNO": "cno",
        "Código do Pais": "codigo_pais",
        "Nome do pais": "nome_pais",
        "Data de início": "data_inicio",
        "Data de inicio da responsabilidade": "data_inicio_responsabilidade",
        "Data de registro": "data_registro",
        "CNO vinculado": "cno_vinculado",
        "CEP": "cep",
        "NI do responsável": "ni_responsavel",
        "Qualificação do responsavel": "qualificacao_codigo",
        "Nome": "nome_obra",
        "Código do municipio": "codigo_municipio",
        "Nome do município": "nome_municipio",
        "Tipo de logradouro": "tipo_logradouro",
        "Logradouro": "logradouro",
        "Número do logradouro": "numero_logradouro",
        "Bairro": "bairro",
        "Estado": "uf",
        "Complemento": "complemento",
        "Unidade de medida": "unidade_medida",
        "Área total": "area_total",
        "Situação": "situacao_codigo",
        "Data da situação": "data_situacao",
        "Nome empresarial": "nome_empresarial",
        "Código de localização": "codigo_localizacao",
    },
    chave_dedup=("cno",),
    particoes=("uf",),
    descartadas={
        "Caixa Postal": "100% nula em 3,6 M de registros",
    },
)

AREAS = TabelaSpec(
    nome="areas",
    arquivo_origem="cno_areas.csv",
    colunas={
        "CNO": "cno",
        "Categoria": "categoria",
        "Destinação": "destinacao",
        "Tipo de obra": "tipo_obra",
        "Tipo de Área": "tipo_area",
        "Tipo de Área Complementar": "tipo_area_complementar",
        "Metragem": "metragem",
    },
    # A fonte não traz identificador de linha: a mesma obra pode ter várias
    # áreas legítimas (principal + complementares). A chave é a linha inteira,
    # e só linhas idênticas em tudo são duplicata de verdade — 21.449 delas.
    chave_dedup=(
        "cno",
        "categoria",
        "destinacao",
        "tipo_obra",
        "tipo_area",
        "tipo_area_complementar",
        "metragem",
    ),
)

CNAES = TabelaSpec(
    nome="cnaes",
    arquivo_origem="cno_cnaes.csv",
    colunas={
        "CNO": "cno",
        "CNAE": "cnae",
        "Data de registro": "data_registro",
    },
    chave_dedup=("cno", "cnae", "data_registro"),
)

VINCULOS = TabelaSpec(
    nome="vinculos",
    arquivo_origem="cno_vinculos.csv",
    colunas={
        "CNO": "cno",
        "Data de início": "data_inicio",
        "Data de fim": "data_fim",
        "Data de registro": "data_registro",
        "Qualificação do contribuinte": "qualificacao_codigo",
        "NI do responsável": "ni_responsavel",
    },
    # 10.873 linhas exatamente idênticas na base.
    chave_dedup=(
        "cno",
        "data_inicio",
        "data_fim",
        "data_registro",
        "qualificacao_codigo",
        "ni_responsavel",
    ),
)

TABELAS: tuple[TabelaSpec, ...] = (OBRAS, AREAS, CNAES, VINCULOS)

# Nome da tabela -> chave usada nos totais de controle do manifesto, para a
# etapa de validação reconciliar contagem por contagem.
TOTAIS_CONTROLE: dict[str, str] = {
    "obras": "cno",
    "areas": "cno_areas",
    "cnaes": "cno_cnaes",
    "vinculos": "cno_vinculos",
}


def tabela_por_nome(nome: str) -> TabelaSpec:
    for spec in TABELAS:
        if spec.nome == nome:
            return spec
    raise KeyError(f"tabela desconhecida: {nome!r}")
