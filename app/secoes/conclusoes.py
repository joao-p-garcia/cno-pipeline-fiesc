"""Seção 10 — o que dá para afirmar, e o que não dá."""

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
        "Com as decisões anteriores no lugar, os números abaixo são defensáveis. "
        "**Sem elas, nenhum deles seria.**",
    )

    # A ordem é uma escalada sobre a mesma pergunta — *o que exatamente se está
    # contando*: contar obras ou medir área (_setor), contar tudo ou só o que
    # está em andamento (_situacao), contar em absoluto ou por habitante
    # (_denominador). Só depois o que a obra é (_destinacao) e o que fica fora.
    _setor()
    _situacao()
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
        "que soma área diz que há **um terço de obra pesada**.\n\n"
        "Tentei fazer uma comparação por CNAE, mas toda a base possui o mesmo."
    )


def _situacao() -> None:
    """A maior parte do que se conta como *obra* já acabou.

    Vinha de um explorador solto na seção do campo nulo, onde o assunto era PF
    contra PJ. Aqui fecha a pergunta que `_setor` abre: o número depende de qual
    universo se está contando.
    """
    st.markdown("### E a maior parte dessas obras já acabou")
    situacao = dados_app.consultar("situacao")
    total = int(situacao["obras"].sum())
    ativas = int(situacao.loc[situacao["situacao"] == "Ativa", "obras"].sum())

    st.altair_chart(
        graficos.barras(
            situacao,
            categoria="situacao",
            valor="obras",
            titulo="Situação cadastral — dois terços das obras estão encerradas",
            subtitulo="a base é o histórico do cadastro, não uma fotografia do canteiro hoje",
            destaque="Ativa",
            rotulo_valor="obras",
        ),
        width="stretch",
    )

    st.markdown(
        f"Das {estilo.numero(total)} obras da base, **{estilo.numero(ativas)} estão "
        f"ativas**, {estilo.percentual(ativas / total)} do total.\n\n"
        "Um número auxilia a entender a atividade econômica das ativas e outro o "
        "estoque construído."
    )

    with ui.explorar("Ver a situação cadastral por UF"):
        uf = ui.seletor_uf("uf_situacao")
        st.altair_chart(
            graficos.barras(
                dados_app.consultar("situacao", uf=uf),
                categoria="situacao",
                valor="obras",
                titulo=f"Situação cadastral — {uf or 'Brasil'}",
                subtitulo="a proporção de ativas varia entre estados",
                destaque="Ativa",
                rotulo_valor="obras",
            ),
            width="stretch",
        )


def _denominador() -> None:
    st.markdown("### Considerar população reordena conclusões")
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
        + "O ranking por habitante mostra outra Santa Catarina, com Itapoá, Passo de "
        "Torres, Maravilha, Pinhalzinho, Balneário Piçarras: litoral norte e Oeste "
        "catarinense."
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
        st.caption("A mediana aqui é calculada sobre as obras, não sobre o mart.")


def _limites() -> None:
    st.markdown("### O que **não** dá para afirmar")
    st.markdown("Análise do que falta e erros nos dados:")
    limites = [
        (
            "O CNO não mede o setor da construção e sim o cadastro dele.",
            "Obra sem matrícula não está aqui. Não consigo tirar o PIB setorial por exemplo.",
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
            "Depende de o cadastro ter sido preenchido com Plus Code, o que varia por "
            "época e por município.",
        ),
        (
            "Área existe para 94% das obras e é autodeclarada.",
            "323 registros impossíveis foram marcados, validei os 3,4 milhões "
            "plausíveis contra nada externo.",
        ),
        (
            "População é de 2026 e as obras são de todos os anos.",
            "A taxa por mil habitantes compara municípios entre si no mesmo instante. "
            "Não consigo tirar uma série histórica.",
        ),
        (
            "Duas obras dizem estar no Brasil e num município chamado EXTERIOR.",
            "A fonte se contradiz, e o pipeline preserva a contradição em vez de escolher um lado.",
        ),
    ]
    for afirmacao, detalhe in limites:
        st.markdown(f"- **{afirmacao}** {detalhe}")
