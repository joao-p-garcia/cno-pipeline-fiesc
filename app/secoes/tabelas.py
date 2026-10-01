"""Seção 2, as quatro tabelas que chegam, e o que cada uma é."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app

TITULO = "As quatro tabelas"

ARQUIVOS = [
    {
        "Arquivo no zip": "cno.csv",
        "Vira": "`obras`",
        "Uma linha é": "uma obra cadastrada",
        "Por obra": "1",
        "O que traz": "identificação, endereço, datas, situação e responsável",
    },
    {
        "Arquivo no zip": "cno_areas.csv",
        "Vira": "`areas`",
        "Uma linha é": "uma área declarada da obra",
        "Por obra": "N",
        "O que traz": "metragem por tipo de área, destinação e tipo de obra",
    },
    {
        "Arquivo no zip": "cno_cnaes.csv",
        "Vira": "`cnaes`",
        "Uma linha é": "uma atividade econômica da obra",
        "Por obra": "N",
        "O que traz": "o código CNAE e a data em que foi registrado",
    },
    {
        "Arquivo no zip": "cno_vinculos.csv",
        "Vira": "`vinculos`",
        "Uma linha é": "um responsável ligado à obra",
        "Por obra": "N",
        "O que traz": "quem responde, em que qualificação e por qual período",
    },
]


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "O pacote traz cinco CSVs, sendo que quatro viram tabela e o quinto traz "
        "as contagens que a Receita declara. Abaixo uma descrição de cada tabela:",
    )

    st.dataframe(pd.DataFrame(ARQUIVOS), hide_index=True, width="stretch")

    st.markdown("### Arquivo de dados totais")
    st.markdown(
        "O quinto arquivo, `cno_totais.csv`, possui quatro números: quantas obras, "
        "CNAEs, áreas e vínculos aquela publicação tem. Esses dados são "
        "posteriormente usados na camada de `cno validate` para reconciliar o que "
        "foi tratado, pois sem uma fonte externa para comparar, é o que permite "
        "validar o dado."
    )
    volumetria = dados_app.consultar("volumetria")
    st.dataframe(
        volumetria.assign(quantas=volumetria["quantas"].map(estilo.numero)),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "As três últimas linhas somam o 1:N depois do tratamento: 4.531.627 áreas "
        "contra 4.553.076 publicadas, e 420.338 vínculos contra 431.211. A diferença "
        "são 21.449 e 10.873 linhas duplicadas na origem."
    )

    ui.decisao(
        achado=(
            "As quatro tabelas somam 12,5 M de linhas, mas são só 3,6 M de obras. "
            "A tabela `areas` tem mais linhas que `obras`, porque uma obra declara "
            "a área principal e quantas complementares quiser."
        ),
        risco=(
            "Juntar as quatro tabelas e contar. Uma obra com três áreas e dois CNAEs "
            "vira seis linhas, e daí toda contagem, soma e média fica multiplicada "
            "por um fator diferente em cada obra. A junção não dá erro, só devolve "
            "um número maior."
        ),
        decisao=(
            "A camada curada reduz o 1:N para uma linha por obra e guarda o que "
            "foi agrupado em `n_areas`, `n_cnaes` e `n_vinculos`. Assim dá para "
            "auditar o que se perdeu, e tem um teste só para garantir isso."
        ),
    )

    with ui.explorar("Ver a volumetria por UF"):
        uf = ui.seletor_uf("uf_tabelas")
        por_uf = dados_app.consultar("volumetria", uf=uf)
        st.dataframe(
            por_uf.assign(quantas=por_uf["quantas"].map(estilo.numero)),
            hide_index=True,
            width="stretch",
        )
        st.markdown("**Quanto o agrupamento para uma linha por obra teve que guardar**")
        cardinalidade = dados_app.consultar("cardinalidade")
        st.dataframe(
            cardinalidade.assign(obras=cardinalidade["obras"].map(estilo.numero)),
            hide_index=True,
            width="stretch",
        )
        st.caption("A obra com mais áreas da base está na última linha.")

    ui.rodape(*ui.vizinhos(__name__))
