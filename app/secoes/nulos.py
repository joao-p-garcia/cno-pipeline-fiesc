"""Seção 2 — o nulo que não é dado faltante, e a junção que não pode inflar."""

from __future__ import annotations

import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "O nulo que não é dado faltante"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "`NI do responsável` está vazio em **dois terços** das obras. A leitura "
        "automática é *coluna suja: imputar ou descartar*. A leitura certa está no "
        "dicionário da Receita: o campo fica em branco quando o responsável é pessoa "
        "física. **O nulo não é ausência de informação — o nulo é a informação.**",
    )

    perfil = dados_app.consultar("responsavel")
    st.altair_chart(
        graficos.barras(
            perfil,
            categoria="tipo",
            valor="obras",
            titulo="Quem responde pela obra",
            subtitulo="o campo em branco em 66% das linhas é pessoa física, não dado perdido",
            destaque="PF",
            rotulo_valor="obras",
        ),
        width="stretch",
    )

    fatia_pf = perfil.loc[perfil["tipo"] == "PF", "obras"].sum() / perfil["obras"].sum()
    ui.decisao(
        vi=(
            f"**{estilo.percentual(fatia_pf)}** das obras não têm NI do responsável "
            "preenchido, e o dicionário da fonte explica por quê: pessoa física não tem "
            "CNPJ para informar ali."
        ),
        quebraria=(
            "Imputar a moda transformaria 2,4 milhões de pessoas físicas em pessoas "
            "jurídicas. Descartar a coluna jogaria fora o recorte mais útil da base. "
            "Nenhuma das duas falhas apareceria num teste."
        ),
        mudou=(
            "O campo virou a coluna derivada `responsavel_tipo` (PF/PJ) na camada tratada, "
            "e a regra `obras.responsavel_tipo_coerente` exige que o tipo continue "
            "refletindo a presença do NI: se alguém um dia preencher o campo *para limpar "
            "o nulo*, a validação reprova e a DAG cai."
        ),
    )

    st.markdown("### Quatro tabelas, duas delas 1:N — e uma linha por obra no fim")
    st.markdown(
        "Obras, áreas, CNAEs e vínculos. Uma obra pode ter **75 áreas declaradas**. Juntar "
        "tudo numa tabela plana multiplicaria a contagem de obras, e **erro de "
        "cardinalidade não dá erro** — dá um número maior, que ninguém questiona."
    )
    cardinalidade = dados_app.consultar("cardinalidade")
    st.dataframe(
        cardinalidade.assign(obras=cardinalidade["obras"].map(estilo.numero)),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "`obras_analitico` tem exatamente uma linha por obra, e o que foi colapsado fica "
        "visível em `n_areas`, `n_cnaes` e `n_vinculos`. A perda de informação é "
        "declarada, não escondida — e há um teste dedicado só a essa propriedade."
    )

    with ui.explorar("Ver a situação cadastral por UF"):
        uf = ui.seletor_uf("uf_nulos")
        situacao = dados_app.consultar("situacao", uf=uf)
        st.altair_chart(
            graficos.barras(
                situacao,
                categoria="situacao",
                valor="obras",
                titulo=f"Situação cadastral — {uf or 'Brasil'}",
                subtitulo="dois terços das obras já estão encerradas",
                destaque="Ativa",
                rotulo_valor="obras",
            ),
            width="stretch",
        )

    ui.rodape(*ui.vizinhos(__name__))
