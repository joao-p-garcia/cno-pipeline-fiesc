"""Seção 3 — a soma que mente por um fator de 312."""

from __future__ import annotations

import altair as alt
import streamlit as st

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
        _grafico_decomposicao(decomposicao),
        width="stretch",
    )
    st.caption(
        "Escala logarítmica: sem ela, a resposta certa vira um traço invisível ao lado "
        "da errada. Cada barra acrescenta um filtro à anterior."
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
                "tudo acima de 1.000 m² empilhado na última barra"
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


# Início do eixo logarítmico. A escala precisa dele: os quatro valores vão de
# 2.839 a 887.114 km², e numa escala linear a resposta certa vira um traço
# invisível ao lado da errada.
PISO_LOG_KM2 = 1_000


def _grafico_decomposicao(decomposicao) -> alt.LayerChart:
    """Régua com ponta, em escala logarítmica, com a resposta certa em azul.

    Não são barras. Barra mede a partir do zero, e o zero não existe em escala
    logarítmica — em Vega-Lite isso não dá erro, dá um gráfico vazio. A régua
    declara de onde parte (`PISO_LOG_KM2`) e o ponto marca onde chega.
    """
    tabela = decomposicao.assign(
        _rotulo=decomposicao["km2"].map(lambda v: f"{estilo.numero(v)} km²"),
        _certa=decomposicao["ordem"] == decomposicao["ordem"].max(),
        _piso=PISO_LOG_KM2,
    )
    cor = alt.condition(alt.datum._certa, alt.value(estilo.AZUL), alt.value(estilo.CINZA))
    base = alt.Chart(tabela).encode(
        y=alt.Y("criterio:N", title=None, sort=list(tabela["criterio"])),
        x=alt.X(
            "km2:Q",
            title="km² (escala logarítmica)",
            scale=alt.Scale(type="log", domain=[PISO_LOG_KM2, 3_000_000]),
        ),
        tooltip=[
            alt.Tooltip("criterio:N", title="critério"),
            alt.Tooltip("km2:Q", title="km²", format=",.1f"),
        ],
    )
    reguas = base.mark_rule(strokeWidth=6, strokeCap="round").encode(x2="_piso:Q", color=cor)
    pontos = base.mark_point(filled=True, size=160, opacity=1).encode(color=cor)
    rotulos = base.mark_text(
        align="left", dx=14, fontSize=11, color=estilo.TINTA_SECUNDARIA
    ).encode(text="_rotulo:N")
    return alt.layer(reguas, pontos, rotulos).properties(
        title=alt.TitleParams(
            "Quantos km² esta base soma — quatro respostas, uma certa",
            subtitle="cada linha acrescenta um filtro à anterior",
            anchor="start",
        ),
        height=150,
    )
