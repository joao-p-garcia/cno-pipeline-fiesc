"""Seção 7 — o que o pipeline construiu com tudo o que as seções anteriores mostraram.

Vem aqui, e não no começo, de propósito. Cada transformação desta seção é
resposta a um problema que já foi visto: o encoding da seção 1, o 1:N da seção
2, o nulo da 3, a soma da 4, o Plus Code da 5, o corte de 2019 da 6. Contada
antes, seria uma lista de etapas; contada agora, é a conta fechando — o leitor
já sabe por que cada linha existe.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import componentes as ui

TITULO = "Das tabelas às camadas"

# As três camadas, e a regra que separa uma da outra. É desenho, não medição:
# os números desta seção vivem no texto, medidos no snapshot corrente.
CAMADAS = [
    {
        "Camada": "**raw**",
        "O que é": "os CSVs como a Receita publica, byte a byte",
        "Regra": "nunca é tocada — é o artefato original, com sha256 por arquivo",
    },
    {
        "Camada": "**staging**",
        "O que é": "as mesmas quatro tabelas, em parquet tipado",
        "Regra": "fiel à origem: trata, mas não interpreta nem agrega",
    },
    {
        "Camada": "**curated**",
        "O que é": "uma linha por obra, mais três marts pré-agregados",
        "Regra": "é aqui que mora a decisão de análise — e só aqui",
    },
]


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Tudo o que as seções anteriores mostraram virou linha de código em algum "
        "lugar. Esta seção é o mapa de onde cada uma foi parar.",
    )

    st.dataframe(pd.DataFrame(CAMADAS), hide_index=True, width="stretch")

    st.markdown("### De raw para staging — tratar sem interpretar")
    st.markdown(
        "O `cno transform` faz cinco coisas, e nenhuma delas é uma decisão de "
        "análise:\n\n"
        "- **transcodifica cp1252 para UTF-8**, porque o DuckDB não lê cp1252 — e "
        "só no arquivo que precisa. Um dos cinco tem bytes na faixa `0x80–0x9F`; "
        "os outros quatro o DuckDB lê direto do original, sem intermediário.\n"
        "- **tipa cada coluna**, em vez de deixar tudo como texto.\n"
        "- **neutraliza as sentinelas de data** — `1900-01-01`, `1970-01-01` e "
        '`0001-01-01` viram nulo. São "desconhecido" escrito como se fosse data, '
        "e mantê-las faria qualquer série temporal ter um pico em 1900.\n"
        "- **desduplica** o que é duplicata de verdade: 21.449 linhas idênticas em "
        "`areas` e 10.873 em `vinculos`. A chave é a linha inteira, porque a fonte "
        "não traz identificador — duas áreas iguais da mesma obra são a mesma área.\n"
        "- **grava parquet particionado por snapshot**, o que faz 1,4 GB de CSV "
        "virarem ~260 MB e permite reprocessar uma safra sem tocar nas outras."
    )
    st.caption(
        "O que **não** acontece aqui: nenhuma junção, nenhuma agregação, nenhuma "
        "regra de negócio. Staging é a origem em formato melhor — se alguém "
        "discordar de uma decisão de análise, a staging continua servindo."
    )

    st.markdown("### De staging para curated — aqui mora a decisão")
    st.markdown(
        "O `cno curate` é onde as escolhas aparecem, e todas elas já foram "
        "justificadas nas seções anteriores:\n\n"
        "- **colapsa o 1:N em uma linha por obra**, guardando `n_areas`, "
        "`n_cnaes` e `n_vinculos` para que a perda seja declarada (seção 2).\n"
        "- **separa pessoa física de jurídica** a partir do campo que era nulo em "
        "66% das linhas (seção 3).\n"
        "- **escolhe a área principal** em vez de somar todas, o que corrigiu um "
        "fator de 312 (seção 4).\n"
        "- **decodifica o Plus Code** em latitude e longitude, e marca quem não "
        "tem ponto — 58,8% da base (seção 5).\n"
        "- **marca `serie_comparavel`** nas obras de 2019 em diante, sem apagar as "
        "anteriores (seção 6).\n"
        "- **materializa três marts** por ano: município, destinação e setor. É o "
        "que este dashboard lê — 133 mil linhas em vez de 3,6 milhões, e é por "
        "isso que cada página responde na hora."
    )

    ui.decisao(
        vi=(
            "Cada problema das seções anteriores tinha duas soluções possíveis: "
            "corrigir no lugar onde apareceu, ou corrigir numa camada e deixar a "
            "anterior intacta."
        ),
        quebraria=(
            "Tratar e interpretar na mesma etapa. No dia em que alguém discordasse "
            "de uma decisão — somar as áreas em vez de pegar a principal, incluir "
            "2018 na série —, a única saída seria **rebaixar os 315 MB e reprocessar "
            "tudo**, porque o dado fiel à origem não existiria mais em lugar nenhum."
        ),
        mudou=(
            "Três camadas com uma regra clara de fronteira. `raw` nunca é tocada, "
            "`staging` trata sem interpretar, `curated` interpreta. Rever uma "
            "decisão de análise custa um `cno curate` de ~35s, não um "
            "reprocessamento — e a etapa de validação roda **entre** as duas, de "
            "modo que nenhum número é publicado em cima de dado reprovado."
        ),
    )

    ui.rodape(*ui.vizinhos(__name__))
