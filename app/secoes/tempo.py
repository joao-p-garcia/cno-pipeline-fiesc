"""Seção 8 — a série triplica em dois anos, e não foi boom de construção."""

from __future__ import annotations

import streamlit as st

from analise import dados as consultas
from analise import estilo

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "Recorte temporal"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Crescimento suspeito entre 2016 e 2019, estabilizando em torno de 300 mil "
        "depois disso. Isso ocorreu porque o CNO substituiu a matrícula CEI e "
        "passou a valer em 21/01/2019. Antes disso ele não existia, e obra antiga "
        "só aparece aqui se alguém registrou depois.",
    )

    serie = dados_app.consultar("obras_por_ano", desde=1995)
    st.altair_chart(
        graficos.serie_temporal(
            serie,
            x="ano",
            y="obras",
            titulo="Obras por ano de início — o degrau de 2018-2019 é cadastral",
            subtitulo=(
                "o ano é o de início declarado da obra, não o de entrada no cadastro; "
                f"o último ano está incompleto (snapshot de {dados_app.conexao().snapshot})"
            ),
            rotulo_valor="obras",
            marcar_ano=consultas.ANO_SERIE_COMPARAVEL,
            rotulo_marca=f"série comparável a partir de {consultas.ANO_SERIE_COMPARAVEL}",
        ),
        width="stretch",
    )

    ui.decisao(
        achado=(
            "Um salto de 3,5× entre 2016 e 2019. Além disso, 45% da base entrou "
            "mais de um ano depois de a obra começar."
        ),
        risco=(
            "Dizer *crescimento de X% desde 2016* seria medir a entrada em vigor de uma "
            "norma, não atividade econômica. Além disso, cada snapshot novo acrescenta "
            "obras antigas registradas com atraso, então a mesma série muda de valor "
            "sem nada ter sido construído."
        ),
        decisao=(
            "Criei a coluna `serie_comparavel`, que marca o que começa em "
            f"{consultas.ANO_SERIE_COMPARAVEL} ou depois. O período anterior continua "
            "acessível, com aviso. Essa data foi escolhida com base na norma **IN RFB "
            "1.845, de 22/11/2018**, com o CNO em vigor a partir de **21/01/2019**."
        ),
    )

    st.markdown("### Último ano com informações incompletas")
    # A comparação com o ano anterior só existe se ele estiver na série. Num
    # recorte pequeno, ou numa base que ainda não tem dois anos, `iloc[0]` numa
    # seleção vazia levanta IndexError e derruba a página.
    ultimo = int(serie["ano"].max())
    anteriores = serie.loc[serie["ano"] == ultimo - 1, "obras"]
    comparacao = (
        f": {estilo.numero(int(serie['obras'].iloc[-1]))} obras contra "
        f"{estilo.numero(int(anteriores.iloc[0]))} no ano inteiro anterior"
        if not anteriores.empty
        else ""
    )
    st.markdown(
        f"O snapshot é de **{dados_app.conexao().snapshot}**, então {ultimo} tem três meses "
        f"e meio faltando{comparacao}."
    )

    with ui.explorar("Comparar UFs e cortar a série"):
        esquerda, direita = st.columns([1, 1])
        with esquerda:
            uf = ui.seletor_uf("uf_tempo")
        with direita:
            comparavel = st.toggle(
                f"Só a série comparável ({consultas.ANO_SERIE_COMPARAVEL}+)",
                value=True,
                key="comparavel_tempo",
            )
        desde = consultas.ANO_SERIE_COMPARAVEL if comparavel else 1995
        st.altair_chart(
            graficos.serie_temporal(
                dados_app.consultar("obras_por_ano", uf=uf, desde=desde),
                x="ano",
                y="obras",
                titulo=f"Obras por ano — {uf or 'Brasil'}",
                subtitulo="mesma definição de ano da seção acima",
                rotulo_valor="obras",
            ),
            width="stretch",
        )
        st.markdown("**A evidência do corte, na própria base**")
        esquerda, direita = st.columns(2)
        with esquerda:
            st.caption("quando as obras entraram no cadastro (`data_registro`)")
            st.dataframe(
                dados_app.consultar("entrada_no_cadastro"), hide_index=True, width="stretch"
            )
        with direita:
            st.caption(
                f"e quando entraram as que **começaram antes de {consultas.ANO_SERIE_COMPARAVEL}**"
            )
            st.dataframe(
                dados_app.consultar("registro_de_obras_antigas"),
                hide_index=True,
                width="stretch",
            )
        st.dataframe(dados_app.consultar("atraso_de_registro"), hide_index=True, width="stretch")
        st.caption(
            "Conclusão: 45% da base entrou mais de ano depois da obra começar."
        )

        st.markdown("**O que fica fora de qualquer série**")
        st.dataframe(dados_app.consultar("datas_ausentes"), hide_index=True, width="stretch")
        st.caption(
            "579 obras sem data de início e 98.440 anteriores a 1990, incluindo datas "
            "sentinela como 1900-01-01. Elas continuam na base, mas fora do recorte "
            "temporal."
        )

    ui.rodape(*ui.vizinhos(__name__))
