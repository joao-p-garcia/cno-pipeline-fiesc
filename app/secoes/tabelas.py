"""Seção 2 — as quatro tabelas que chegam, e o que cada uma é.

Existe porque a seção anterior mostra **como** o dado chega (um zip, cp1252) e
as seguintes já discutem problemas específicos. Faltava o mapa: o que há dentro
do pacote, o que cada arquivo significa e como eles se ligam. Sem isso, quem
assiste ouve "obras", "áreas" e "vínculos" sem saber que os três não têm o mesmo
tamanho nem a mesma chave.

O argumento da seção é a **cardinalidade**. `cno.csv` tem uma linha por obra; os
outros três têm N por obra. É essa assimetria que torna "juntar tudo numa tabela
só" a decisão mais cara do pipeline, e é ela que a seção 7 retoma.

O bloco do gabarito mora aqui, e não na seção 1 como já morou: `cno_totais.csv`
declara uma contagem **por tabela**, e contagem por tabela não significa nada
para quem ainda não sabe que tabelas existem. Junto das quatro, ele fecha o
raciocínio — e a reconciliação do 1:N vira a prova de que a leitura está certa.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app

TITULO = "As quatro tabelas"

# O que cada arquivo do pacote é. Descrição, não número: os números vêm da
# camada curada, logo abaixo, e redigitá-los aqui criaria duas versões da mesma
# contagem. O que não dá para consultar é o *significado*, e é só isso que mora
# nesta tabela.
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
        "O pacote traz **cinco** CSVs. Quatro viram tabela; o quinto é o gabarito "
        "com que a Receita confere o próprio arquivo. Antes de discutir qualquer "
        "problema do dado, vale saber o que é cada coisa — e que elas **não têm o "
        "mesmo tamanho**.",
    )

    st.dataframe(pd.DataFrame(ARQUIVOS), hide_index=True, width="stretch")

    st.markdown("### A fonte publica o próprio gabarito")
    st.markdown(
        "O quinto arquivo, `cno_totais.csv`, não vira tabela: são quatro números — "
        "quantas obras, CNAEs, áreas e vínculos aquela publicação tem. É pequeno o "
        "bastante para passar despercebido e é a coisa mais valiosa do pacote: "
        "**sem oráculo externo, validação é o pipeline conferindo contra si mesmo**."
    )
    volumetria = dados_app.consultar("volumetria")
    st.dataframe(
        volumetria.assign(quantas=volumetria["quantas"].map(estilo.numero)),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "As três últimas linhas somam o 1:N depois do tratamento: 4.531.627 áreas contra "
        "4.553.076 publicadas, 420.338 vínculos contra 431.211. A diferença são 21.449 e "
        "10.873 **linhas exatamente duplicadas** na origem — e o número bate ao registro."
    )

    ui.decisao(
        vi=(
            "As quatro tabelas somam **12,5 M de linhas**, mas só 3,6 M de obras. "
            "`areas` tem **mais linhas que `obras`** — uma obra declara a área "
            "principal e quantas complementares quiser."
        ),
        quebraria=(
            "Juntar as quatro num `JOIN` e contar. Cada obra com três áreas e dois "
            "CNAEs vira **seis linhas**, e a partir daí toda contagem, soma e média "
            "está multiplicada por um fator que varia de obra para obra. O `JOIN` "
            "não dá erro; dá um número maior."
        ),
        mudou=(
            "A camada curada colapsa o 1:N para **uma linha por obra** e guarda o "
            "que foi colapsado em `n_areas`, `n_cnaes` e `n_vinculos`. A perda é "
            "declarada e auditável, não silenciosa — e há teste dedicado só a essa "
            "propriedade."
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
        st.markdown("**Quanta informação o colapso para uma linha por obra teve que guardar**")
        cardinalidade = dados_app.consultar("cardinalidade")
        st.dataframe(
            cardinalidade.assign(obras=cardinalidade["obras"].map(estilo.numero)),
            hide_index=True,
            width="stretch",
        )
        st.caption("A obra com mais áreas da base está na última linha.")

    ui.rodape(*ui.vizinhos(__name__))
