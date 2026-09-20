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

TITULO = "As três camadas"

# As três camadas, e a regra que separa uma da outra. É desenho, não medição:
# os números desta seção vivem no texto, medidos no snapshot corrente.
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
        "Regra": "é aqui que ficam as decisões de análise, e só aqui",
    },
]


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Cada problema das seções anteriores virou código em algum lugar. Aqui "
        "mostro onde cada um foi parar, e por que separei o tratamento em três "
        "camadas.",
    )

    st.dataframe(pd.DataFrame(CAMADAS), hide_index=True, width="stretch")

    st.markdown("### De raw para staging: tratar sem interpretar")
    st.markdown(
        "O `cno transform` faz cinco coisas, e nenhuma é decisão de análise:\n\n"
        "- **converte cp1252 para UTF-8**, porque o DuckDB não lê cp1252, e só no "
        "arquivo que precisa. Um dos cinco tem bytes na faixa `0x80` a `0x9F`. "
        "Os outros quatro o DuckDB lê direto do original.\n"
        "- **tipa cada coluna**, em vez de deixar tudo como texto.\n"
        "- **anula as datas sentinela**: `1900-01-01`, `1970-01-01` e "
        '`0001-01-01` viram nulo. São "desconhecido" escrito como se fosse data, '
        "e manter isso daria um pico em 1900 em qualquer série.\n"
        "- **remove duplicatas de verdade**: 21.449 linhas idênticas em `areas` e "
        "10.873 em `vinculos`. A chave é a linha inteira, porque a fonte não traz "
        "identificador, então duas áreas iguais da mesma obra são a mesma área.\n"
        "- **grava parquet particionado por snapshot**, o que faz 1,4 GB de CSV "
        "virarem ~260 MB e permite reprocessar uma safra sem mexer nas outras."
    )
    st.caption(
        "O que **não** acontece aqui: nenhuma junção, nenhuma agregação e nenhuma "
        "regra de negócio. A staging é a origem em formato melhor. Se alguém "
        "discordar de uma decisão de análise, ela continua servindo."
    )

    st.markdown("### De staging para curated: aqui ficam as decisões")
    st.markdown(
        "É no `cno curate` que as escolhas aparecem, e todas já foram "
        "justificadas nas seções anteriores:\n\n"
        "- **agrupa o 1:N em uma linha por obra**, guardando `n_areas`, "
        "`n_cnaes` e `n_vinculos` para que a perda seja declarada (seção 2).\n"
        "- **separa pessoa física de jurídica** a partir do campo que era nulo em "
        "66% das linhas (seção 5).\n"
        "- **escolhe a área principal** em vez de somar todas, o que corrigiu um "
        "fator de 312 (seção 6).\n"
        "- **decodifica o Plus Code** em latitude e longitude, e marca quem não "
        "tem ponto, que são 58,8% da base (seção 7).\n"
        "- **marca `serie_comparavel`** nas obras de 2019 em diante, sem apagar as "
        "anteriores (seção 8).\n"
        "- **materializa três marts** por ano: município, destinação e setor. É o "
        "que este dashboard lê, 133 mil linhas em vez de 3,6 milhões, e por isso "
        "cada página responde na hora."
    )

    ui.decisao(
        achado=(
            "Cada problema tinha duas saídas: corrigir no lugar onde apareceu, ou "
            "corrigir numa camada e deixar a anterior intacta."
        ),
        risco=(
            "Tratar e interpretar na mesma etapa. No dia em que alguém discordar de "
            "uma decisão, tipo somar as áreas em vez de pegar a principal, a única "
            "saída seria **baixar os 315 MB de novo e reprocessar tudo**, porque o "
            "dado fiel à origem não existiria mais."
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
