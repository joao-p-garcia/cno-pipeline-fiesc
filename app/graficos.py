"""Construtores de gráfico do dashboard.

Altair, e não matplotlib como no notebook, porque aqui o gráfico é interativo: um
gráfico numa página web sem *hover* desperdiça o meio. As cores, a grade e a
tipografia saem de `analise/estilo.py` — a mesma paleta do caderno, para que o
mesmo achado tenha a mesma cara nos dois lugares.

Três regras que valem para tudo neste arquivo:

* **Série única, cor única.** Barra maior não ganha cor mais forte.
* **Ênfase em vez de arco-íris.** O que o gráfico defende fica azul; o resto,
  cinza. Quando há duas séries, há legenda.
* **Um eixo só.** Obras e metros quadrados nunca dividem a mesma escala.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from analise import estilo, malha

ALTURA_BARRA = 26


def _titulo(titulo: str, subtitulo: str | None = None) -> alt.TitleParams:
    return alt.TitleParams(titulo, subtitle=subtitulo or "", anchor="start")


# Separadores brasileiros para os eixos e tooltips. O Vega formata número no
# padrão inglês por default; esta é a opção que o vega-embed lê para trocar o
# locale, e ela viaja dentro do próprio gráfico, em `usermeta`. Quem renderiza o
# gráfico fora do navegador (um PNG, por exemplo) ignora — é a única parte do
# estilo que depende de onde o gráfico é desenhado.
LOCALE_BR = {"decimal": ",", "thousands": ".", "grouping": [3], "currency": ["R$", ""]}


def _publicar(chart):
    """Último passo de todo gráfico daqui: carimba o locale e devolve."""
    return chart.properties(usermeta={"embedOptions": {"formatLocale": LOCALE_BR}})


def _altura(categorias: int, por_categoria: int) -> int:
    """Altura fixa a partir do número de categorias.

    O jeito idiomático seria `alt.Step`, que deixa o Vega-Lite dimensionar
    sozinho — mas **`step` não vale em gráfico com camadas**, e todo gráfico daqui
    tem pelo menos duas (a marca e o rótulo). O Vega-Lite não reclama: devolve um
    gráfico vazio. Calcular a altura aqui é feio e é o que funciona.
    """
    return max(120, categorias * por_categoria)


def barras(
    df: pd.DataFrame,
    *,
    categoria: str,
    valor: str,
    titulo: str,
    subtitulo: str | None = None,
    destaque: str | list[str] | None = None,
    rotulo_valor: str | None = None,
    ordenar: bool = True,
    cor: str = estilo.AZUL,
) -> alt.LayerChart:
    """Barras horizontais com rótulo direto no fim de cada uma.

    Horizontais porque os rótulos deste projeto são nomes ("Residencial
    unifamiliar", "Serviços especializados para construção") e nome girado 45° é
    o jeito mais rápido de tornar um gráfico ilegível.
    """
    dados = df.copy()
    alvos = {destaque} if isinstance(destaque, str) else set(destaque or ())
    dados["_destaque"] = dados[categoria].isin(alvos)
    dados["_rotulo"] = dados[valor].map(lambda v: estilo.numero(v, 0 if abs(v) >= 100 else 1))

    ordem = alt.Sort("-x") if ordenar else None
    base = alt.Chart(dados).encode(
        y=alt.Y(f"{categoria}:N", title=None, sort=ordem),
        x=alt.X(f"{valor}:Q", title=rotulo_valor or valor, axis=alt.Axis(grid=True)),
        tooltip=[alt.Tooltip(c, title=c.replace("_", " ")) for c in df.columns],
    )
    if alvos:
        marcas = base.mark_bar(height=ALTURA_BARRA, cornerRadiusEnd=3).encode(
            color=alt.condition(
                alt.datum._destaque, alt.value(estilo.AZUL), alt.value(estilo.CINZA)
            )
        )
    else:
        marcas = base.mark_bar(height=ALTURA_BARRA, cornerRadiusEnd=3, color=cor)
    rotulos = base.mark_text(align="left", dx=6, fontSize=11, color=estilo.TINTA_SECUNDARIA).encode(
        text="_rotulo:N"
    )
    return _publicar(
        (marcas + rotulos).properties(
            title=_titulo(titulo, subtitulo), height=_altura(len(dados), ALTURA_BARRA + 12)
        )
    )


def barras_comparadas(
    df: pd.DataFrame,
    *,
    categoria: str,
    series: dict[str, str],
    titulo: str,
    subtitulo: str | None = None,
    rotulo_valor: str,
) -> alt.Chart:
    """Duas medidas por categoria, na mesma escala e com legenda.

    Só é legítimo quando as duas medidas **são comparáveis** — aqui, duas
    participações percentuais. Duas grandezas diferentes viram dois gráficos.
    """
    longo = df.melt(
        id_vars=[categoria], value_vars=list(series), var_name="medida", value_name="valor"
    )
    longo["medida"] = longo["medida"].map(series)
    return _publicar(
        alt.Chart(longo)
        .mark_bar(height=ALTURA_BARRA / 2, cornerRadiusEnd=2)
        .encode(
            y=alt.Y(f"{categoria}:N", title=None, sort=None),
            yOffset=alt.YOffset("medida:N", sort=list(series.values())),
            x=alt.X("valor:Q", title=rotulo_valor),
            color=alt.Color(
                "medida:N",
                title=None,
                sort=list(series.values()),
                scale=alt.Scale(range=[estilo.AZUL, estilo.LARANJA]),
                legend=alt.Legend(orient="bottom", direction="horizontal"),
            ),
            tooltip=[categoria, "medida", alt.Tooltip("valor:Q", format=".1f")],
        )
        .properties(
            title=_titulo(titulo, subtitulo),
            height=_altura(df[categoria].nunique(), (ALTURA_BARRA + 12) * len(series)),
        )
    )


def serie_temporal(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    titulo: str,
    subtitulo: str | None = None,
    rotulo_valor: str,
    marcar_ano: int | None = None,
    rotulo_marca: str = "",
) -> alt.LayerChart:
    """Linha com marcador em cada ponto e régua vertical opcional.

    O ponto em cima da linha não é enfeite: sem ele, um ano faltante vira um
    segmento reto e some.
    """
    base = alt.Chart(df).encode(
        x=alt.X(f"{x}:O", title=None, axis=alt.Axis(labelAngle=0, values=_anos_ticks(df[x]))),
        y=alt.Y(f"{y}:Q", title=rotulo_valor),
        tooltip=[alt.Tooltip(c, title=c.replace("_", " ")) for c in df.columns],
    )
    camadas = [
        base.mark_line(color=estilo.AZUL, strokeWidth=2),
        base.mark_point(color=estilo.AZUL, filled=True, size=45),
    ]
    if marcar_ano is not None and marcar_ano in set(df[x]):
        regua = pd.DataFrame({x: [marcar_ano], "rotulo": [rotulo_marca]})
        camadas.append(
            alt.Chart(regua)
            .mark_rule(color=estilo.LARANJA, strokeWidth=2)
            .encode(x=alt.X(f"{x}:O"))
        )
        camadas.append(
            # Alinhado à direita, encostando na régua pela esquerda: alinhado à
            # esquerda, um rótulo desses transborda a área do gráfico sempre que a
            # marca cai perto do fim da série — que é justamente o caso aqui.
            alt.Chart(regua)
            .mark_text(align="right", dx=-8, color=estilo.LARANJA, fontSize=11, fontWeight="bold")
            .encode(x=alt.X(f"{x}:O"), y=alt.value(12), text="rotulo:N")
        )
    return _publicar(alt.layer(*camadas).properties(title=_titulo(titulo, subtitulo), height=300))


def _anos_ticks(serie: pd.Series) -> list[int]:
    """Um rótulo a cada cinco anos, mais o último — 30 rótulos não cabem.

    O último só entra se não colidir com o múltiplo de cinco anterior: `2025` e
    `2026` lado a lado viram um borrão.
    """
    anos = sorted(int(a) for a in serie.unique())
    if not anos:
        return []
    marcos = [a for a in anos if a % 5 == 0]
    ultimo = anos[-1]
    if not marcos or ultimo - marcos[-1] >= 2:
        marcos.append(ultimo)
    return marcos


def histograma(
    df: pd.DataFrame, *, titulo: str, subtitulo: str | None = None, mediana: float | None = None
) -> alt.LayerChart:
    """Distribuição de área, com a mediana marcada."""
    base = (
        alt.Chart(df)
        .mark_bar(color=estilo.AZUL, width=6)
        .encode(
            x=alt.X("faixa_inicio:Q", title="área da obra (m²)"),
            y=alt.Y("obras:Q", title="obras"),
            tooltip=[
                alt.Tooltip("faixa_inicio:Q", title="a partir de (m²)"),
                alt.Tooltip("obras:Q", title="obras", format=","),
            ],
        )
    )
    camadas = [base]
    if mediana is not None:
        marca = pd.DataFrame({"x": [mediana], "rotulo": [f"mediana {estilo.numero(mediana)} m²"]})
        camadas.append(
            alt.Chart(marca).mark_rule(color=estilo.LARANJA, strokeWidth=2).encode(x="x:Q")
        )
        camadas.append(
            alt.Chart(marca)
            .mark_text(
                align="left", dx=8, dy=-4, color=estilo.LARANJA, fontSize=11, fontWeight="bold"
            )
            .encode(x="x:Q", y=alt.value(10), text="rotulo:N")
        )
    return _publicar(alt.layer(*camadas).properties(title=_titulo(titulo, subtitulo), height=280))


def mapa(
    pontos: pd.DataFrame,
    malha_uf: dict,
    *,
    titulo: str,
    subtitulo: str | None = None,
    largura: int = 760,
    altura: int = 460,
) -> alt.LayerChart:
    """Bolhas sobre a malha municipal do IBGE.

    Cada bolha é um município, posicionado na **mediana das coordenadas
    plausíveis** das suas obras — não no centroide oficial. É a mesma âncora que a
    curadoria usa para recuperar Plus Code curto, então o mapa mostra o dado que o
    pipeline de fato tem, não uma aproximação cartográfica por cima dele.
    """
    fundo = alt.Chart(alt.Data(values=malha_uf["features"])).mark_geoshape(
        fill=estilo.FUNDO_MAPA, stroke=estilo.GRADE, strokeWidth=0.6
    )
    bolhas = (
        alt.Chart(pontos)
        .mark_circle(color=estilo.AZUL, opacity=0.55, stroke=estilo.SUPERFICIE, strokeWidth=0.8)
        .encode(
            longitude="longitude:Q",
            latitude="latitude:Q",
            size=alt.Size(
                "obras:Q",
                title="obras",
                scale=alt.Scale(range=[10, 900]),
                # Poucos degraus e dentro do mapa: a legenda padrão do Vega abre
                # oito círculos e rouba um terço da largura do gráfico.
                legend=alt.Legend(
                    orient="bottom-left", symbolType="circle", values=[1000, 5000, 10000]
                ),
            ),
            tooltip=[
                alt.Tooltip("municipio:N", title="município"),
                alt.Tooltip("obras:Q", title="obras", format=","),
                alt.Tooltip("geocodificadas:Q", title="com ponto no mapa", format=","),
                alt.Tooltip("area_km2:Q", title="área (km²)", format=".2f"),
            ],
        )
    )
    # A projeção vai na camada, nunca em cada sublayer: duas projeções irmãs não
    # se conversam, e o resultado é a malha sumir e os pontos desabarem num
    # amontoado no meio da tela. Centro e escala são calculados a partir da
    # própria malha — ver `malha.enquadramento` para o porquê de não haver ajuste
    # automático aqui.
    centro, escala = malha.enquadramento(malha_uf, largura, altura)
    return _publicar(
        alt.layer(fundo, bolhas)
        .project(type="mercator", center=list(centro), scale=escala)
        .properties(title=_titulo(titulo, subtitulo), width=largura, height=altura)
    )
