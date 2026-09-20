"""Seção 2 — o nulo que não é dado faltante, e a junção que não pode inflar."""

from __future__ import annotations

import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "O campo nulo que não é dado faltante"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "O campo `NI do responsável` está vazio em **dois terços** das obras. A "
        "primeira reação é tratar como coluna suja e imputar ou descartar. Mas o "
        "dicionário da Receita explica: o campo fica em branco quando o "
        "responsável é pessoa física. **O vazio aqui é a informação.**",
    )

    perfil = dados_app.consultar("responsavel")
    st.altair_chart(
        graficos.barras(
            perfil,
            categoria="tipo",
            valor="obras",
            titulo="Quem responde pela obra",
            subtitulo="o campo em branco em 66% das linhas é pessoa física",
            destaque="PF",
            rotulo_valor="obras",
        ),
        width="stretch",
    )

    fatia_pf = perfil.loc[perfil["tipo"] == "PF", "obras"].sum() / perfil["obras"].sum()
    ui.decisao(
        achado=(
            f"**{estilo.percentual(fatia_pf)}** das obras não têm NI do responsável "
            "preenchido. O dicionário da fonte explica: pessoa física não tem CNPJ "
            "para informar ali."
        ),
        risco=(
            "Imputar a moda transformaria 2,4 milhões de pessoas físicas em jurídicas. "
            "Descartar a coluna jogaria fora um dos recortes mais úteis da base. "
            "Nenhum dos dois erros apareceria num teste."
        ),
        decisao=(
            "Criei a coluna `responsavel_tipo` (PF/PJ) na camada tratada. A regra "
            "`obras.responsavel_tipo_coerente` exige que o tipo continue refletindo a "
            "presença do NI. Se alguém preencher o campo para limpar o nulo, a "
            "validação reprova e a DAG cai."
        ),
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
