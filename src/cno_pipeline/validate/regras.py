"""Regras de validação da camada tratada.

Cada regra é um SELECT que devolve **as linhas que a violam**. Conjunto vazio
significa regra cumprida. O executor conta, amostra exemplos e decide o código
de saída — então acrescentar uma regra é escrever uma consulta, sem mexer em
nenhuma mecânica.

As tabelas entram como `{obras}`, `{areas}`, `{cnaes}` e `{vinculos}`, que o
executor substitui pelos `read_parquet` do snapshot em avaliação.

Sobre severidade: `ERRO` é violação de contrato — se acontecer, a camada tratada
não está confiável e o pipeline falha. `AVISO` é característica conhecida da
fonte que queremos medir e acompanhar, mas que não invalida a carga. Marcar tudo
como erro tornaria a validação inútil, porque um cadastro público de 3,6 milhões
de registros sempre tem sujeira; marcar tudo como aviso a tornaria decorativa.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..transform.schema import (
    QUALIFICACOES,
    SITUACOES,
    UFS_BRASIL,
)


class Severidade(StrEnum):
    """Erro reprova a validação; aviso é medido e reportado sem reprovar."""

    ERRO = "erro"
    AVISO = "aviso"


@dataclass(frozen=True)
class Regra:
    nome: str
    descricao: str
    severidade: Severidade
    # SELECT que devolve as linhas violadoras.
    violacoes: str
    # Colunas a mostrar quando houver violação, para o relatório ser acionável.
    amostra: tuple[str, ...] = ()


def _lista(valores) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(valores))


_SITUACOES = _lista(SITUACOES)
_QUALIFICACOES = _lista(QUALIFICACOES)
_UFS = _lista(UFS_BRASIL)

# Todas as flags booleanas da camada tratada. Um NULL em qualquer uma delas é
# armadilha: `WHERE NOT flag` descartaria essas linhas em silêncio.
_FLAGS_OBRAS = (
    "obra_ativa",
    "no_exterior",
    "uf_indefinida",
    "tem_plus_code",
    "area_suspeita",
    "datas_incoerentes",
)


REGRAS: tuple[Regra, ...] = (
    # -- chave primária e unicidade -------------------------------------
    Regra(
        nome="obras.cno_unico",
        descricao="CNO é chave primária da tabela de obras",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT cno, count(*) AS ocorrencias
            FROM {obras} GROUP BY cno HAVING count(*) > 1
        """,
        amostra=("cno", "ocorrencias"),
    ),
    Regra(
        nome="obras.cno_preenchido",
        descricao="toda obra tem CNO",
        severidade=Severidade.ERRO,
        violacoes="SELECT * FROM {obras} WHERE cno IS NULL OR trim(cno) = ''",
        amostra=("nome_obra", "uf"),
    ),
    # -- integridade referencial ----------------------------------------
    Regra(
        nome="areas.cno_existe_em_obras",
        descricao="toda área pertence a uma obra cadastrada",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT a.cno FROM {areas} a
            WHERE NOT EXISTS (SELECT 1 FROM {obras} o WHERE o.cno = a.cno)
        """,
        amostra=("cno",),
    ),
    Regra(
        nome="cnaes.cno_existe_em_obras",
        descricao="todo CNAE pertence a uma obra cadastrada",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT c.cno FROM {cnaes} c
            WHERE NOT EXISTS (SELECT 1 FROM {obras} o WHERE o.cno = c.cno)
        """,
        amostra=("cno",),
    ),
    Regra(
        nome="vinculos.cno_existe_em_obras",
        descricao="todo vínculo pertence a uma obra cadastrada",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT v.cno FROM {vinculos} v
            WHERE NOT EXISTS (SELECT 1 FROM {obras} o WHERE o.cno = v.cno)
        """,
        amostra=("cno",),
    ),
    # -- domínios --------------------------------------------------------
    Regra(
        nome="obras.situacao_no_dominio",
        descricao="situação está entre os códigos publicados pela Receita",
        severidade=Severidade.ERRO,
        violacoes=f"""
            SELECT cno, situacao_codigo FROM {{obras}}
            WHERE situacao_codigo IS NOT NULL
              AND situacao_codigo NOT IN ({_SITUACOES})
        """,
        amostra=("cno", "situacao_codigo"),
    ),
    Regra(
        nome="obras.situacao_traduzida",
        descricao="todo código de situação recebeu descrição legível",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT cno, situacao_codigo FROM {obras}
            WHERE situacao_codigo IS NOT NULL AND situacao IS NULL
        """,
        amostra=("cno", "situacao_codigo"),
    ),
    Regra(
        nome="obras.uf_valida",
        descricao="UF preenchida é uma das 27 unidades federativas",
        severidade=Severidade.ERRO,
        violacoes=f"""
            SELECT cno, uf FROM {{obras}}
            WHERE uf IS NOT NULL AND uf NOT IN ({_UFS})
        """,
        amostra=("cno", "uf"),
    ),
    Regra(
        nome="obras.qualificacao_no_dominio",
        descricao="qualificação do responsável está no domínio publicado",
        severidade=Severidade.ERRO,
        violacoes=f"""
            SELECT cno, qualificacao_codigo FROM {{obras}}
            WHERE qualificacao_codigo IS NOT NULL
              AND qualificacao_codigo NOT IN ({_QUALIFICACOES})
        """,
        amostra=("cno", "qualificacao_codigo"),
    ),
    # -- flags de dois valores -------------------------------------------
    Regra(
        nome="obras.flags_nunca_nulas",
        descricao="flags booleanas são TRUE ou FALSE, nunca NULL",
        severidade=Severidade.ERRO,
        violacoes="SELECT cno FROM {obras} WHERE "
        + " OR ".join(f"{f} IS NULL" for f in _FLAGS_OBRAS),
        amostra=("cno",),
    ),
    # -- coerência interna -----------------------------------------------
    Regra(
        nome="obras.responsavel_tipo_coerente",
        descricao="responsavel_tipo reflete a presença do NI",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT cno, responsavel_tipo, ni_responsavel FROM {obras}
            WHERE (ni_responsavel IS NULL AND responsavel_tipo <> 'PF')
               OR (ni_responsavel IS NOT NULL AND responsavel_tipo <> 'PJ')
        """,
        amostra=("cno", "responsavel_tipo"),
    ),
    Regra(
        nome="obras.sem_datas_sentinela",
        descricao="sentinelas de data desconhecida viraram NULL",
        severidade=Severidade.ERRO,
        violacoes="""
            SELECT cno, data_inicio FROM {obras}
            WHERE data_inicio IN (DATE '1970-01-01', DATE '1900-01-01')
               OR data_situacao IN (DATE '1970-01-01', DATE '1900-01-01')
        """,
        amostra=("cno", "data_inicio"),
    ),
    Regra(
        nome="obras.area_nao_negativa",
        descricao="área total não é negativa",
        severidade=Severidade.ERRO,
        violacoes="SELECT cno, area_total FROM {obras} WHERE area_total < 0",
        amostra=("cno", "area_total"),
    ),
    # -- avisos: sujeira conhecida da fonte, medida e acompanhada ---------
    Regra(
        nome="obras.datas_coerentes",
        descricao="obra não começa depois da data da situação",
        severidade=Severidade.AVISO,
        violacoes="SELECT cno, data_inicio, data_situacao FROM {obras} WHERE datas_incoerentes",
        amostra=("cno", "data_inicio", "data_situacao"),
    ),
    Regra(
        nome="obras.area_plausivel",
        descricao="área em m² dentro de ordem de grandeza plausível",
        severidade=Severidade.AVISO,
        violacoes="SELECT cno, area_total, nome_obra FROM {obras} WHERE area_suspeita",
        amostra=("cno", "area_total"),
    ),
    Regra(
        nome="obras.uf_identificada",
        descricao="obra no Brasil tem UF identificada",
        severidade=Severidade.AVISO,
        violacoes="""
            SELECT cno, uf_origem, nome_municipio FROM {obras}
            WHERE uf IS NULL AND NOT no_exterior
        """,
        amostra=("cno", "uf_origem", "nome_municipio"),
    ),
    Regra(
        nome="obras.data_inicio_nao_futura",
        descricao="obra não começa no futuro",
        severidade=Severidade.AVISO,
        violacoes="SELECT cno, data_inicio FROM {obras} WHERE data_inicio > current_date",
        amostra=("cno", "data_inicio"),
    ),
    Regra(
        nome="areas.metragem_preenchida",
        descricao="área tem metragem informada",
        severidade=Severidade.AVISO,
        violacoes="SELECT cno, tipo_area FROM {areas} WHERE metragem IS NULL",
        amostra=("cno", "tipo_area"),
    ),
    Regra(
        nome="vinculos.periodo_coerente",
        descricao="vínculo não termina antes de começar",
        severidade=Severidade.AVISO,
        violacoes="""
            SELECT cno, data_inicio, data_fim FROM {vinculos}
            WHERE data_fim IS NOT NULL AND data_inicio IS NOT NULL
              AND data_fim < data_inicio
        """,
        amostra=("cno", "data_inicio", "data_fim"),
    ),
)
