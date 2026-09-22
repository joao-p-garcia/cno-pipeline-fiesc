"""Seção 5 — o nulo que não é dado faltante.

Primeira seção depois da virada: as quatro anteriores montam o pipeline, daqui
em diante o assunto é o que a base diz. A frase de abertura marca essa troca —
sem ela a seção caía em `NI do responsável` logo depois de um diagrama de DAG.
"""

from __future__ import annotations

import streamlit as st

from analise import estilo

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "Campos nulos"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Com parte da arquitetura decidida, continuamos a análise exploratória "
        "para a tomada de decisões que serão úteis para os insights finais.\n\n"
        "O campo `NI do responsável` está vazio em **dois terços** das obras. "
        "Inicialmente ia descartar essa coluna ou as linhas, mas descobri que "
        "esse vazio significa que é uma pessoa física.",
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
            "preenchido."
        ),
        risco=(
            "Descartar a coluna pode jogar fora um recorte útil."
        ),
        decisao=(
            "Criei a coluna `responsavel_tipo` (PF/PJ) na camada tratada. A regra "
            "`obras.responsavel_tipo_coerente` exige que o tipo continue refletindo a "
            "presença do NI. Se alguém preencher o campo para limpar o nulo, a "
            "validação reprova e a DAG cai."
        ),
    )

    # O explorador desta seção mostrava situação cadastral (Ativa/Encerrada),
    # que é bom achado e assunto nenhum desta seção — a UF aparecia do nada,
    # num texto sobre PF e PJ. Mudou de casa: agora abre a seção de conclusões,
    # onde a pergunta é justamente *o que se está contando*. Aqui ficou o
    # recorte que responde à pergunta da seção.
    with ui.explorar("Ver a divisão PF/PJ por UF"):
        uf = ui.seletor_uf("uf_nulos")
        st.altair_chart(
            graficos.barras(
                dados_app.consultar("responsavel", uf=uf),
                categoria="tipo",
                valor="obras",
                titulo=f"Quem responde pela obra — {uf or 'Brasil'}",
                subtitulo="a proporção varia por estado, e a coluna existe para permitir a dúvida",
                destaque="PF",
                rotulo_valor="obras",
            ),
            width="stretch",
        )

    ui.rodape(*ui.vizinhos(__name__))