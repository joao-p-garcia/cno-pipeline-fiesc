"""Seção 3 — a soma que mente por um fator de 312."""

from __future__ import annotations

import streamlit as st

from analise import dados as consultas
from analise import estilo

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "A soma que mente"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        "Seção 3 de 6",
        TITULO,
        "Pergunta de primeiro slide: *quantos metros quadrados esta base soma?* "
        "`SUM(area_total)` responde na hora — e responde errado, por **dois motivos "
        "independentes**, cada um capaz de estragar o número sozinho.",
    )

    decomposicao = dados_app.consultar("decomposicao_area")
    cru = float(decomposicao["km2"].iloc[0])
    certo = float(decomposicao["km2"].iloc[-1])

    st.altair_chart(
        graficos.decomposicao_log(
            decomposicao,
            titulo="Quantos km² esta base soma — quatro respostas, uma certa",
            subtitulo="as duas do meio isolam um problema cada; a última aplica os dois",
        ),
        width="stretch",
    )
    st.caption(
        "Escala logarítmica: sem ela, a resposta certa vira um traço invisível ao lado "
        "da errada. As duas linhas do meio isolam um problema cada — a unidade "
        "misturada e a área implausível —, e a última aplica os dois."
    )

    ui.numeros(
        [
            ("soma crua", f"{estilo.numero(cru)} km²", "SUM(area_total), sem pensar"),
            ("soma publicável", f"{estilo.numero(certo)} km²", "só m², sem as áreas implausíveis"),
            # O denominador pode ser zero: basta um recorte em que nenhuma obra tenha
            # área em metro quadrado. É raro no Brasil inteiro e deixa de ser raro
            # assim que alguém filtra por UF pequena — e uma divisão por zero derruba
            # a página inteira, não só o número.
            (
                "fator de erro",
                f"{estilo.numero(cru / certo)}×" if certo else "—",
                "entre uma resposta e a outra",
            ),
        ]
    )

    ui.decisao(
        vi=(
            "Primeiro: **a coluna mistura unidades** — metro quadrado em 94% das linhas, e "
            "quilômetro, metro cúbico, quilowatt e kVA no resto. Segundo: **323 obras "
            "declaram área impossível**, a maior com 555.555.555.555 m², cerca de 65 vezes "
            "a área do Brasil."
        ),
        quebraria=(
            "Nenhum dos filtros resolve sozinho: só tirar as implausíveis ainda deixa "
            "49.286 km² (soma de unidades diferentes); só pegar o que está em m² ainda "
            "deixa 840.668 km² (a digitação continua lá). Um `SUM` desavisado publicaria "
            "um número 312 vezes maior que o certo."
        ),
        mudou=(
            "A camada curada tem uma coluna `area_m2` que **só existe quando a unidade é "
            "metro quadrado e a área não é suspeita**. A área declarada continua ao lado, "
            "intacta, com a unidade — marcar, nunca apagar. Só `area_m2` é agregável, e é "
            "a única que os marts somam."
        ),
    )

    st.markdown("### E a média de 834 m² não descreve obra nenhuma")
    quantis = dados_app.consultar("quantis_area")
    mediana = float(quantis["mediana"].iloc[0])
    media = float(quantis["media"].iloc[0])

    st.altair_chart(
        graficos.histograma(
            dados_app.consultar("histograma_area"),
            titulo="Área construída por obra",
            subtitulo=(
                f"mediana {estilo.numero(mediana)} m² · média {estilo.numero(media)} m² — "
                f"tudo acima de {estilo.numero(consultas.TETO_HISTOGRAMA_M2)} m² "
                "empilhado na última barra"
            ),
            mediana=mediana,
        ),
        width="stretch",
    )
    st.caption(
        "Metade das obras tem até 135 m²; um quarto tem até 70. A média é puxada pelo 1% "
        "acima de 12.049 m² e não descreve caso nenhum — por isso os marts guardam "
        "mediana, e as faixas de `faixa_area` foram cortadas na distribuição real."
    )

    with ui.explorar("Explorar unidades, faixas e as áreas implausíveis"):
        uf = ui.seletor_uf("uf_area")
        esquerda, direita = st.columns(2)
        with esquerda:
            st.markdown("**O que está declarado em cada unidade**")
            st.dataframe(
                dados_app.consultar("perfil_unidades", uf=uf),
                hide_index=True,
                width="stretch",
            )
        with direita:
            st.markdown("**Quantis de `area_m2`**")
            st.dataframe(
                dados_app.consultar("quantis_area", uf=uf).T.rename(columns={0: "m²"}),
                width="stretch",
            )
        st.altair_chart(
            graficos.barras(
                dados_app.consultar("faixas_area", uf=uf),
                categoria="faixa_area",
                valor="obras",
                titulo=f"Obras por faixa de área — {uf or 'Brasil'}",
                rotulo_valor="obras",
                ordenar=False,
            ),
            width="stretch",
        )
        st.markdown("**As maiores áreas declaradas da base — marcadas, não excluídas**")
        st.dataframe(
            dados_app.consultar("areas_implausiveis", limite=10),
            hide_index=True,
            width="stretch",
        )

    ui.rodape(anterior="O nulo que não é dado faltante", proxima="O endereço vem em Plus Code")
