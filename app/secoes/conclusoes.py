"""Seção 6 — o que dá para afirmar, e o que não dá."""

from __future__ import annotations

import streamlit as st

from analise import dados as consultas
from analise import estilo

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "O que dá para afirmar"

UF_FOCO = "SC"
POPULACAO_MINIMA = 10_000


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "Com as cinco decisões anteriores no lugar, os números abaixo são defensáveis. "
        "**Nenhum deles seria, sem elas.**",
    )

    _setor()
    _denominador()
    _destinacao()
    _limites()

    ui.rodape(*ui.vizinhos(__name__))


def _setor() -> None:
    st.markdown("### Contar obras e medir área respondem coisas diferentes")
    divisoes = dados_app.consultar("divisoes_cnae")
    st.altair_chart(
        graficos.barras_comparadas(
            divisoes,
            categoria="nome",
            series={"pct_obras": "% das obras", "pct_area": "% dos metros quadrados"},
            titulo="Infraestrutura é 8% das obras e 28% da área construída",
            subtitulo="mesma escala nos dois: são duas participações, não duas grandezas",
            rotulo_valor="% do total",
        ),
        width="stretch",
    )
    st.markdown(
        "Um relatório que conta registros diz que o setor é **residencial pulverizado**; um "
        "que soma área diz que há **um terço de obra pesada**. As duas frases são "
        "verdadeiras, e citar uma sem a outra é meia verdade.\n\n"
        "Vale registrar o que **não** funcionou: agrupar pela *seção* da CNAE daria uma "
        "linha só — 100% da base é seção F (Construção). O recorte útil é a divisão."
    )


def _denominador() -> None:
    st.markdown("### O denominador reordena o mapa inteiro")
    if not dados_app.metadados_referencia():
        st.info(
            "A tabela de referência do IBGE não está gerada, então não há denominador. "
            "Gere com `python analise/construir_municipios.py`."
        )
        return

    municipios = dados_app.consultar("municipios", uf=UF_FOCO, comparavel=True)
    elegiveis = municipios[municipios["populacao"] >= POPULACAO_MINIMA]
    absoluto = elegiveis.nlargest(10, "obras")[["nome_ibge", "obras"]]
    relativo = elegiveis.nlargest(10, "obras_por_mil_hab")[["nome_ibge", "obras_por_mil_hab"]]

    esquerda, direita = st.columns(2)
    with esquerda:
        st.altair_chart(
            graficos.barras(
                absoluto,
                categoria="nome_ibge",
                valor="obras",
                titulo=f"{UF_FOCO} — obras em números absolutos",
                subtitulo="os grandes centros, como esperado",
                rotulo_valor="obras",
                cor=estilo.CINZA,
            ),
            width="stretch",
        )
    with direita:
        st.altair_chart(
            graficos.barras(
                relativo,
                categoria="nome_ibge",
                valor="obras_por_mil_hab",
                titulo=f"{UF_FOCO} — obras por mil habitantes",
                subtitulo=(
                    "série comparável, municípios com "
                    f"{POPULACAO_MINIMA // 1000} mil habitantes ou mais"
                ),
                rotulo_valor="obras por mil habitantes",
            ),
            width="stretch",
        )

    repetidos = sorted(set(absoluto["nome_ibge"]) & set(relativo["nome_ibge"]))
    st.markdown(
        f"**Das dez posições, {10 - len(repetidos)} trocam.** "
        + (f"Só {', '.join(repetidos)} sobrevive à mudança de denominador. " if repetidos else "")
        + "O ranking por habitante mostra outra Santa Catarina — Itapoá, Passo de Torres, "
        "Maravilha, Pinhalzinho, Balneário Piçarras: **litoral norte e Oeste catarinense**, "
        "dois padrões que o número absoluto escondia por completo."
    )

    regioes = dados_app.consultar("regioes", uf=UF_FOCO)
    st.altair_chart(
        graficos.barras(
            regioes,
            categoria="regiao",
            valor="obras_por_mil_hab",
            titulo=f"{UF_FOCO} — obras por mil habitantes, por região intermediária",
            subtitulo="Chapecó constrói mais que o dobro da região da capital, por habitante",
            destaque="Chapecó",
            rotulo_valor="obras por mil habitantes",
        ),
        width="stretch",
    )

    with ui.explorar("Ver o ranking completo, por UF"):
        uf = ui.seletor_uf("uf_conclusoes")
        comparavel = st.toggle(
            f"Só a série comparável ({consultas.ANO_SERIE_COMPARAVEL}+)",
            value=True,
            key="comp_conclusoes",
        )
        tabela = dados_app.consultar("municipios", uf=uf, comparavel=comparavel)
        st.dataframe(
            tabela[
                [
                    "uf",
                    "nome_ibge",
                    "obras",
                    "ativas",
                    "populacao",
                    "obras_por_mil_hab",
                    "regiao_intermediaria",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        st.markdown("**Por UF**")
        st.dataframe(
            dados_app.consultar("ranking_ufs", comparavel=comparavel),
            hide_index=True,
            width="stretch",
        )


def _destinacao() -> None:
    st.markdown("### Para que serve a obra")
    destinos = dados_app.consultar("destinacoes").head(8)
    st.altair_chart(
        graficos.barras(
            destinos,
            categoria="destinacao",
            valor="obras",
            titulo="Seis em cada dez obras são casa",
            subtitulo="destinação da maior área principal declarada",
            destaque="Residencial unifamiliar",
            rotulo_valor="obras",
        ),
        width="stretch",
    )
    with ui.explorar("Ver destinação e tamanho típico por UF"):
        uf = ui.seletor_uf("uf_destinacao")
        tabela = dados_app.consultar("destinacoes", uf=uf).head(12)
        st.dataframe(
            tabela.assign(
                obras=tabela["obras"].map(estilo.numero),
                area_km2=tabela["area_km2"].map(lambda v: estilo.numero(v, 2)),
                area_mediana_m2=tabela["area_mediana_m2"].map(lambda v: estilo.numero(v, 1)),
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "A mediana aqui é calculada sobre as obras, não sobre o mart: mediana de "
            "medianas não é mediana, e um número inventado por conveniência é exatamente "
            "o que este projeto não publica."
        )


def _limites() -> None:
    st.markdown("### O que **não** dá para afirmar")
    st.markdown("Uma análise honesta declara os limites antes que alguém os descubra.")
    limites = [
        (
            "O CNO não mede o setor da construção; mede o cadastro dele.",
            "Obra que não precisa de matrícula não está aqui. Serve para *onde há obra "
            "cadastrada*, não para PIB setorial.",
        ),
        (
            "O ano é o de início declarado, não o de execução.",
            "Uma obra cadastrada em 2022 com início em 1997 entra em 1997.",
        ),
        (
            "Antes de 2019 a série não é comparável, e o último ano nunca está fechado.",
            "O CNO não existia antes de nov/2018, então o passado é subcontado — e "
            "**não é estável**: cresce a cada snapshot, conforme obras antigas são "
            "registradas com atraso. Do outro lado, corte de calendário.",
        ),
        (
            "58,8% das obras não têm ponto no mapa, e a ausência não é aleatória.",
            "Depende de o cadastro ter sido preenchido com Plus Code, o que varia por época "
            "e por município. Todo mapa aqui é de um subconjunto.",
        ),
        (
            "Área existe para 94% das obras e é autodeclarada.",
            "323 registros impossíveis foram marcados; não há como validar os 3,4 milhões "
            "plausíveis contra nada externo.",
        ),
        (
            "População é de 2026 e as obras são de todos os anos.",
            "A taxa por mil habitantes compara municípios entre si no mesmo instante. Não é "
            "série histórica.",
        ),
        (
            "Duas obras dizem estar no Brasil e num município chamado EXTERIOR.",
            "A fonte se contradiz, e o pipeline preserva a contradição em vez de escolher um lado.",
        ),
    ]
    for afirmacao, detalhe in limites:
        st.markdown(f"- **{afirmacao}** {detalhe}")
