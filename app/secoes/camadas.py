"""Seção 9, o que o pipeline construiu com tudo o que as seções anteriores mostraram."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cno_pipeline.validate import REGRAS, Severidade

from .. import componentes as ui

TITULO = "Transformação dos dados"

CAMADAS = [
    {
        "Camada": "**raw**",
        "O que é": "os CSVs como a Receita publica, byte a byte",
        "Regra": "nunca é tocada, é o arquivo original com sha256 por arquivo",
    },
    {
        "Camada": "**staging**",
        "O que é": "as mesmas quatro tabelas, em parquet tipado",
        "Regra": "fiel à origem: trata, mas não interpreta nem agrega",
    },
    {
        "Camada": "**curated**",
        "O que é": "uma linha por obra, mais três marts pré-agregados",
        "Regra": "onde ficam as decisões de análise",
    },
]


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Seção dedicada a explicar como ficaram as camadas de dados.",
    )

    st.dataframe(pd.DataFrame(CAMADAS), hide_index=True, width="stretch")

    st.markdown("### De raw para staging")
    st.markdown(
        "O `cno transform` faz cinco coisas:\n\n"
        "- **converte cp1252 para UTF-8**, porque o DuckDB não lê cp1252, e só no "
        "arquivo que precisa. Um dos cinco tem bytes na faixa `0x80` a `0x9F`. "
        "Os outros quatro o DuckDB lê direto do original.\n"
        "- **tipa cada coluna**, em vez de deixar tudo como texto.\n"
        "- **anula as datas sentinela**: `1900-01-01`, `1970-01-01` e "
        "`0001-01-01` viram nulo.\n"
        "- **remove duplicatas de verdade**: 21.449 linhas idênticas em `areas` e "
        "10.873 em `vinculos`.\n"
        "- **grava parquet particionado por snapshot**, o que faz 1,4 GB de CSV "
        "virarem ~260 MB e permite reprocessar uma safra de dados sem mexer nas "
        "outras."
    )
    st.caption(
        "O que **não** acontece aqui: nenhuma junção, nenhuma agregação e nenhuma regra de negócio."
    )

    st.markdown("### De staging para curated")
    st.markdown(
        "O `cno curate` aplica as decisões tomadas mostradas nas seções "
        "anteriores:\n\n"
        "- **agrupa o 1:N em uma linha por obra**, guardando `n_areas`, "
        "`n_cnaes` e `n_vinculos` (seção 2).\n"
        "- **separa pessoa física de jurídica** a partir do campo que era nulo em "
        "66% das linhas (seção 5).\n"
        "- **escolhe a área principal** em vez de somar todas, o que corrigiu um "
        "fator de 312x (seção 6).\n"
        "- **decodifica o Plus Code** em latitude e longitude, e marca quem não "
        "tem ponto, que são 58,8% da base (seção 7).\n"
        "- **marca `serie_comparavel`** nas obras de 2019 em diante, sem apagar as "
        "anteriores (seção 8).\n"
        "- **materializa três marts** por ano: município, destinação e setor. É o "
        "que este Streamlit lê, 133 mil linhas em vez de 3,6 milhões, e por isso "
        "cada página responde na hora, rodando local."
    )

    _validacao()

    ui.decisao(
        achado=("Corrigir o problema direto ou passar pra próxima camada com avisos."),
        risco=(
            "Tratar e interpretar na mesma etapa, se houver mudança nas regras de "
            "negócio, é necessário **baixar os 315 MB de novo e reprocessar tudo**."
        ),
        decisao=(
            "Três camadas com regra clara. A `raw` nunca é tocada, a `staging` trata "
            "sem interpretar e a `curated` interpreta. Rever uma decisão de análise "
            "custa um `cno curate` de ~35s em vez de um reprocessamento inteiro. E "
            "a validação roda **entre** as duas, então nenhum número é publicado em "
            "cima de dado reprovado."
        ),
    )

    ui.rodape(*ui.vizinhos(__name__))


def _validacao() -> None:
    """As regras de validação, lidas do pacote que as executa."""
    erros = sum(1 for r in REGRAS if r.severidade is Severidade.ERRO)

    st.markdown("### Validação dos dados")
    st.markdown(
        f"Roda **entre a staging e a curated**, com {len(REGRAS)} regras. Cada uma "
        "é um `SELECT` que devolve as linhas que a violam, e resultado de conjunto "
        "vazio significa regra cumprida.\n\n"
        f"**{erros} são `erro`** e falham a DAG: o `cno validate` sai com "
        f"código 1, a task falha e o `cno curate` não roda. **{len(REGRAS) - erros} "
        "são `aviso`**, característica conhecida da fonte e não falham a DAG."
    )

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Regra": regra.nome,
                    "O que exige": regra.descricao,
                    "Severidade": regra.severidade.value,
                }
                for regra in REGRAS
            ]
        ),
        hide_index=True,
        width="stretch",
        height=460,
    )
    st.caption(
        "Gerada a partir de `cno_pipeline.validate.REGRAS`, o mesmo objeto que o "
        "pipeline executa. Quando uma regra falha, o relatório sai com exemplos "
        "das linhas que violaram a validação."
    )

    st.markdown(
        "Além disso, o `cno_totais.csv` traz a contagem oficial de cada tabela, a "
        "extração grava esses números no manifesto e a validação os confronta com "
        "o que foi carregado."
    )
