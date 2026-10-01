"""Construtores de gráfico do dashboard."""

from __future__ import annotations

import altair as alt
import pandas as pd

from analise import estilo, malha

ALTURA_BARRA = 20

ESPACO_BARRA = 14

ALTURA_BARRA_AGRUPADA = 12


def _titulo(titulo: str, subtitulo: str | None = None) -> alt.TitleParams:
    return alt.TitleParams(titulo, subtitle=subtitulo or "", anchor="start")


def _tooltips(df: pd.DataFrame, casas: dict[str, int] | None = None) -> tuple[pd.DataFrame, list]:
    """Tooltips com o número **já escrito em português**, como texto."""
    casas = casas or {}
    tabela = df.copy()
    tooltips = []
    for coluna in df.columns:
        if str(coluna).startswith("_"):
            continue
        titulo = str(coluna).replace("_", " ")
        numerica = pd.api.types.is_numeric_dtype(df[coluna]) and not pd.api.types.is_bool_dtype(
            df[coluna]
        )
        if not numerica:
            tooltips.append(alt.Tooltip(f"{coluna}:N", title=titulo))
            continue
        destino = f"_tt_{coluna}"
        decimais = casas.get(str(coluna), 0)
        tabela[destino] = df[coluna].map(
            lambda v, d=decimais: "—" if pd.isna(v) else estilo.numero(v, d)
        )
        tooltips.append(alt.Tooltip(f"{destino}:N", title=titulo))
    return tabela, tooltips


ALTURA_MOLDURA = 70


def _altura_fixa(area_de_plotagem: int) -> int:
    """Altura a pedir para obter `area_de_plotagem` de área útil."""
    return area_de_plotagem + ALTURA_MOLDURA


def _altura(categorias: int, por_categoria: int) -> int:
    """Altura fixa a partir do número de categorias."""
    return max(120, categorias * por_categoria) + ALTURA_MOLDURA


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
    """Barras horizontais com rótulo direto no fim de cada uma."""
    dados = df.copy()
    alvos = {destaque} if isinstance(destaque, str) else set(destaque or ())
    dados["_destaque"] = dados[categoria].isin(alvos)
    dados["_rotulo"] = dados[valor].map(lambda v: estilo.numero(v, 0 if abs(v) >= 100 else 1))
    dados, dicas = _tooltips(dados, casas={valor: 0})

    ordem = alt.Sort("-x") if ordenar else None
    base = alt.Chart(dados).encode(
        y=alt.Y(f"{categoria}:N", title=None, sort=ordem),
        x=alt.X(f"{valor}:Q", title=rotulo_valor or valor, axis=alt.Axis(grid=True)),
        tooltip=dicas,
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
    return (marcas + rotulos).properties(
        title=_titulo(titulo, subtitulo), height=_altura(len(dados), ALTURA_BARRA + ESPACO_BARRA)
    )


PISO_LOG_KM2 = 1_000


def decomposicao_log(df: pd.DataFrame, *, titulo: str, subtitulo: str) -> alt.LayerChart:
    """Régua com ponta, em escala logarítmica, com a última linha em azul."""
    tabela = df.assign(
        _rotulo=df["km2"].map(lambda v: f"{estilo.numero(v)} km²"),
        _certa=[False] * (len(df) - 1) + [True],
        _piso=PISO_LOG_KM2,
    )
    tabela, dicas = _tooltips(tabela, casas={"km2": 1})
    cor = alt.condition(alt.datum._certa, alt.value(estilo.AZUL), alt.value(estilo.CINZA))
    base = alt.Chart(tabela).encode(
        y=alt.Y("criterio:N", title=None, sort=list(tabela["criterio"])),
        x=alt.X(
            "km2:Q",
            title="km² (escala logarítmica)",
            scale=alt.Scale(type="log", domain=[PISO_LOG_KM2, 3_000_000]),
        ),
        tooltip=dicas,
    )
    reguas = base.mark_rule(strokeWidth=6, strokeCap="round").encode(x2="_piso:Q", color=cor)
    pontos = base.mark_point(filled=True, size=160, opacity=1).encode(color=cor)
    rotulos = base.mark_text(
        align="left", dx=14, fontSize=11, color=estilo.TINTA_SECUNDARIA
    ).encode(text="_rotulo:N")
    return alt.layer(reguas, pontos, rotulos).properties(
        title=_titulo(titulo, subtitulo),
        height=_altura(len(tabela), ALTURA_BARRA + ESPACO_BARRA),
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
    """Duas medidas por categoria, na mesma escala e com legenda."""
    longo = df.melt(
        id_vars=[categoria], value_vars=list(series), var_name="medida", value_name="valor"
    )
    longo["medida"] = longo["medida"].map(series)
    longo, dicas = _tooltips(longo, casas={"valor": 1})
    return (
        alt.Chart(longo)
        .mark_bar(height=ALTURA_BARRA_AGRUPADA, cornerRadiusEnd=2)
        .encode(
            y=alt.Y(f"{categoria}:N", title=None, sort=None),
            yOffset=alt.YOffset("medida:N", sort=list(series.values())),
            x=alt.X("valor:Q", title=rotulo_valor),
            color=alt.Color(
                "medida:N",
                title=None,
                sort=list(series.values()),
                scale=alt.Scale(range=[estilo.AZUL, estilo.DOURADO]),
                legend=alt.Legend(orient="bottom", direction="horizontal"),
            ),
            tooltip=dicas,
        )
        .properties(
            title=_titulo(titulo, subtitulo),
            height=_altura(df[categoria].nunique(), (ALTURA_BARRA + ESPACO_BARRA) * len(series)),
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
    """Linha com marcador em cada ponto e régua vertical opcional."""
    tabela, dicas = _tooltips(df)
    base = alt.Chart(tabela).encode(
        x=alt.X(
            f"{x}:O",
            title=None,
            axis=alt.Axis(
                labelAngle=0,
                values=_anos_ticks(df[x]),
                labelExpr=estilo.ROTULO_SEM_SEPARADOR,
            ),
        ),
        y=alt.Y(f"{y}:Q", title=rotulo_valor),
        tooltip=dicas,
    )
    camadas = [
        base.mark_line(color=estilo.AZUL, strokeWidth=2),
        base.mark_point(color=estilo.AZUL, filled=True, size=45),
    ]
    if marcar_ano is not None and marcar_ano in set(df[x]):
        regua = pd.DataFrame({x: [marcar_ano], "rotulo": [rotulo_marca]})
        camadas.append(
            alt.Chart(regua)
            .mark_rule(color=estilo.DOURADO, strokeWidth=2)
            .encode(x=alt.X(f"{x}:O"))
        )
        camadas.append(
            alt.Chart(regua)
            .mark_text(align="right", dx=-8, color=estilo.DOURADO, fontSize=11, fontWeight="bold")
            .encode(x=alt.X(f"{x}:O"), y=alt.value(12), text="rotulo:N")
        )
    return alt.layer(*camadas).properties(
        title=_titulo(titulo, subtitulo), height=_altura_fixa(300)
    )


def _anos_ticks(serie: pd.Series) -> list[int]:
    """Um rótulo a cada cinco anos, mais o último."""
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
    tabela, dicas = _tooltips(df)
    base = (
        alt.Chart(tabela)
        .mark_bar(color=estilo.AZUL, width=6)
        .encode(
            x=alt.X("faixa_inicio:Q", title="área da obra (m²)"),
            y=alt.Y("obras:Q", title="obras"),
            tooltip=dicas,
        )
    )
    camadas = [base]
    if mediana is not None:
        marca = pd.DataFrame({"x": [mediana], "rotulo": [f"mediana {estilo.numero(mediana)} m²"]})
        camadas.append(
            alt.Chart(marca).mark_rule(color=estilo.DOURADO, strokeWidth=2).encode(x="x:Q")
        )
        camadas.append(
            alt.Chart(marca)
            .mark_text(
                align="left", dx=8, dy=-4, color=estilo.DOURADO, fontSize=11, fontWeight="bold"
            )
            .encode(x="x:Q", y=alt.value(10), text="rotulo:N")
        )
    return alt.layer(*camadas).properties(
        title=_titulo(titulo, subtitulo), height=_altura_fixa(280)
    )


def mapa(
    pontos: pd.DataFrame,
    malha_uf: dict,
    *,
    titulo: str,
    subtitulo: str | None = None,
    largura: int = 760,
    altura: int = 460,
) -> alt.LayerChart:
    """Bolhas sobre a malha municipal do IBGE."""
    fundo = alt.Chart(alt.Data(values=malha_uf["features"])).mark_geoshape(
        fill=estilo.FUNDO_MAPA, stroke=estilo.GRADE, strokeWidth=0.6
    )
    pontos, dicas = _tooltips(pontos, casas={"area_km2": 2, "latitude": 3, "longitude": 3})
    bolhas = (
        alt.Chart(pontos)
        .mark_circle(
            color=estilo.AZUL,
            opacity=estilo.OPACIDADE_BOLHA,
            stroke=estilo.SUPERFICIE,
            strokeWidth=0.8,
        )
        .encode(
            longitude="longitude:Q",
            latitude="latitude:Q",
            size=alt.Size(
                "obras:Q",
                title="obras",
                scale=alt.Scale(range=[10, 900]),
                legend=alt.Legend(
                    orient="bottom-left",
                    symbolType="circle",
                    values=[1000, 5000, 10000],
                    labelExpr=estilo.ROTULO_NUMERO_BR,
                ),
            ),
            tooltip=dicas,
        )
    )
    centro, escala = malha.enquadramento(malha_uf, largura, altura)
    return (
        alt.layer(fundo, bolhas)
        .project(type="mercator", center=list(centro), scale=escala)
        .properties(title=_titulo(titulo, subtitulo), width=largura, height=altura)
    )
