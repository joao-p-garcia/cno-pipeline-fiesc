"""Seção 7, localização das obras."""

from __future__ import annotations

import streamlit as st

from analise import dados as consultas
from analise import estilo, malha

from .. import componentes as ui
from .. import dados_app, graficos

TITULO = "Localização das obras"

UF_PADRAO = "SC"


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "O campo `Código de localização` traz um **Plus Code** (Open Location Code, "
        "do Google) em 2,1 milhões de registros. Porém, alguns não decodificam "
        "(estão errados) e outros apontam para localizações erradas.",
    )

    funil = dados_app.consultar("funil_geocodificacao")
    total = dados_app.consultar("total_obras")
    com_mais, decodificaram, plausiveis = (int(v) for v in funil["obras"])

    st.altair_chart(
        graficos.barras(
            funil,
            categoria="etapa",
            valor="obras",
            titulo="Cobertura da geocodificação",
            subtitulo=f"sobre {estilo.numero(total)} obras",
            destaque="cai no município certo",
            rotulo_valor="obras",
            ordenar=False,
        ),
        width="stretch",
    )

    ui.numeros(
        [
            ("plus code", estilo.percentual(com_mais / total), "tudo que contém um '+'"),
            ("decodifica", estilo.percentual(decodificaram / total), "tudo que decodifica"),
            (
                "cobertura tratada",
                estilo.percentual(plausiveis / total),
                "só o ponto que cai no município declarado",
            ),
        ]
    )

    ui.decisao(
        achado=(
            "**48.436 Plus Codes (3,7% dos decodificados) são válidos e apontam para o "
            "lugar errado.** São 39 mil a mais de 500 km do município declarado, "
            "alguns no Japão. O prefixo de área foi digitado trocado e o código "
            "continua sintaticamente válido."
        ),
        risco=(
            "Mostrar pontos no lugar errado no mapa e publicar uma cobertura 43% maior "
            "que a real, sem nenhum erro aparecer."
        ),
        decisao=(
            "Coluna `geo_distancia_municipio_km`, com a distância até a mediana do "
            "município, e `geo_plausivel`, que corta em "
            f"{consultas.LIMITE_PLAUSIVEL_KM} km. Para plotar, filtra-se por "
            "`geo_plausivel`. Dessa forma, 41,2% de cobertura."
        ),
    )

    st.markdown("### Tratamento das áreas")
    st.dataframe(dados_app.consultar("perfil_geo"), hide_index=True, width="stretch")
    st.caption(
        "Os **códigos curtos recuperados são mais limpos que os completos**: todos os "
        "226.854 são plausíveis, com distância máxima de 76 km, que é o limite "
        "geométrico de um código de 4 caracteres."
    )

    st.markdown("### Mapa tratado das obras")
    uf = st.selectbox(
        "UF no mapa",
        dados_app.consultar("ufs_disponiveis"),
        index=dados_app.consultar("ufs_disponiveis").index(UF_PADRAO),
        key="uf_mapa",
    )
    pontos = dados_app.consultar("mapa_municipios", uf=uf)
    if malha.disponivel() and dados_app.metadados_referencia() and not pontos.empty:
        prefixo = dados_app.consultar("prefixo_ibge", uf=uf)
        st.altair_chart(
            graficos.mapa(
                pontos,
                dados_app.contornos_uf(prefixo),
                titulo=f"Cada bolha é um município ({uf})",
                subtitulo=(
                    "posição = mediana das coordenadas plausíveis das obras do município; "
                    "tamanho = número de obras. Malha municipal: IBGE."
                ),
            ),
            width="stretch",
        )
    else:
        st.info(
            "A malha municipal não está gerada, então o mapa fica de fora e a tabela abaixo "
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
        st.markdown("**Os pontos mais distantes da base, todos com código válido**")
        st.dataframe(
            dados_app.consultar("pontos_fora", limite=10),
            hide_index=True,
            width="stretch",
        )

    ui.rodape(*ui.vizinhos(__name__))
