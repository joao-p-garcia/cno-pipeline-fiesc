"""Seção 4 — o endereço vem em Plus Code, e alguns apontam para o Japão."""

from __future__ import annotations

import streamlit as st

from analise import dados as consultas
from analise import estilo, malha

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "O endereço vem em Plus Code"

# Prefixo do código do IBGE para Santa Catarina — o mapa abre em SC porque é o
# recorte que interessa à FIESC; o seletor troca para qualquer outra UF.
UF_PADRAO = "SC"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        "Seção 4 de 6",
        TITULO,
        "`Código de localização` traz um **Plus Code** (Open Location Code, do Google) em "
        "2,1 milhões de registros. Dá para geocodificar a base inteira sem nenhum serviço "
        "pago — a decodificação é aritmética e roda offline. A tentação é anunciar *59% da "
        "base geocodificada*. **O caminho até o número honesto tem três degraus.**",
    )

    # Os três degraus vêm de `dados.funil_geocodificacao`, não de três contagens
    # remontadas aqui: é o número mais citado da narrativa, e o caderno mostra
    # exatamente este. Duas cópias do mesmo SQL divergiriam em silêncio.
    funil = dados_app.consultar("funil_geocodificacao")
    total = dados_app.consultar("total_obras")
    com_mais, decodificaram, plausiveis = (int(v) for v in funil["obras"])

    st.altair_chart(
        graficos.barras(
            funil,
            categoria="etapa",
            valor="obras",
            titulo="Cobertura da geocodificação — três números, e só o último é publicável",
            subtitulo=f"sobre {estilo.numero(total)} obras",
            destaque="cai no município certo",
            rotulo_valor="obras",
            ordenar=False,
        ),
        width="stretch",
    )

    ui.numeros(
        [
            ("cobertura ingênua", estilo.percentual(com_mais / total), "tudo que contém um '+'"),
            ("cobertura bruta", estilo.percentual(decodificaram / total), "tudo que decodifica"),
            (
                "cobertura publicável",
                estilo.percentual(plausiveis / total),
                "só o ponto que cai no município declarado",
            ),
        ]
    )

    ui.decisao(
        vi=(
            "**48.436 Plus Codes (3,7% dos decodificados) são válidos e apontam para o "
            "lugar errado** — 39 mil a mais de 500 km do município declarado, alguns no "
            "Japão. O prefixo de área foi digitado trocado, e o código continua "
            "sintaticamente perfeito."
        ),
        quebraria=(
            "Um mapa com obras catarinenses em Kyushu, e uma cobertura anunciada 43% maior "
            "do que a real. Nada disso levanta exceção: o código **decodifica**."
        ),
        mudou=(
            "Existem duas colunas: `geo_distancia_municipio_km`, com a distância até a "
            "mediana do município, e `geo_plausivel`, que corta em "
            f"{consultas.LIMITE_PLAUSIVEL_KM} km. O ponto errado "
            "**continua gravado** — quem plota filtra por `geo_plausivel`, quem investiga "
            "tem o caso na mão. A cobertura publicada é 41,2%."
        ),
    )

    st.markdown("### O detalhe que inverte a intuição")
    st.dataframe(dados_app.consultar("perfil_geo"), hide_index=True, width="stretch")
    st.caption(
        "Os **códigos curtos recuperados são mais limpos que os completos**: todos os "
        "226.854 são plausíveis, com distância máxima de 76 km — exatamente o limite "
        "geométrico de um código de 4 caracteres. A recuperação ancorada na mediana do "
        "município é mais confiável que o dado que veio 'bom'."
    )

    st.markdown("### O mapa que sobra depois disso")
    uf = st.selectbox(
        "UF no mapa",
        dados_app.consultar("ufs_disponiveis"),
        index=dados_app.consultar("ufs_disponiveis").index(UF_PADRAO),
        key="uf_mapa",
    )
    pontos = dados_app.consultar("mapa_municipios", uf=uf)
    # A malha e a tabela de municípios saem do mesmo gerador, mas o mapa depende
    # das duas: uma dá o desenho, a outra dá o prefixo de UF do IBGE.
    if malha.disponivel() and dados_app.metadados_referencia() and not pontos.empty:
        prefixo = dados_app.consultar("prefixo_ibge", uf=uf)
        st.altair_chart(
            graficos.mapa(
                pontos,
                dados_app.contornos_uf(prefixo),
                titulo=f"{uf} — cada bolha é um município",
                subtitulo=(
                    "posição = mediana das coordenadas plausíveis das obras do município; "
                    "tamanho = número de obras. Malha municipal: IBGE."
                ),
            ),
            width="stretch",
        )
    else:
        st.info(
            "A malha municipal não está gerada — o mapa fica de fora e a tabela abaixo "
            "continua valendo. Gere com `python analise/construir_municipios.py`."
        )
        st.dataframe(pontos, hide_index=True, width="stretch")

    with ui.explorar("Ver as distâncias e os pontos que caíram longe"):
        st.altair_chart(
            graficos.barras(
                dados_app.consultar("distancia_geo"),
                categoria="faixa",
                valor="pontos",
                titulo="Distância entre o ponto decodificado e a mediana do município",
                destaque=f"até {consultas.LIMITE_PLAUSIVEL_KM} km (plausível)",
                rotulo_valor="pontos",
                ordenar=False,
            ),
            width="stretch",
        )
        st.markdown("**Os pontos mais distantes da base — todos decodificam perfeitamente**")
        st.dataframe(
            dados_app.consultar("pontos_fora", limite=10),
            hide_index=True,
            width="stretch",
        )

    ui.rodape(anterior="A soma que mente", proxima="A série que triplica")
