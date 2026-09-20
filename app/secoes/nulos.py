"""Seção 5 — o nulo que não é dado faltante.

É a primeira seção depois da virada. As quatro anteriores montam a esteira; a
partir daqui o assunto é o que a base diz, e cada achado volta como uma linha
de código no sistema que acabou de ser apresentado.

A seção 4 já anuncia essa dobradiça no próprio texto, mas quem assiste não lê
docstring: o parágrafo de abertura aqui existe para que a troca de gênero
aconteça na tela, e não só na cabeça de quem escreveu. Sem ele a seção começava
a falar de `NI do responsável` logo depois de um diagrama de DAG, e o salto
ficava seco.
"""

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
        "Até aqui o trabalho foi montar a esteira. Ela roda sozinha às quatro da "
        "manhã, e isso troca a pergunta: em vez de *como trago o dado*, passa a "
        "ser *o que o dado diz*. **As próximas quatro seções são achados da base — "
        "e cada um deles virou uma linha de código na esteira que você acabou de "
        "ver.** Este é o primeiro.\n\n"
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
