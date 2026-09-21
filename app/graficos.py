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

# Espessura da barra, com teto de 24px. Barra que preenche a faixa inteira faz o
# gráfico virar uma parede: a sobra da banda é ar, e é o ar que separa uma barra
# da seguinte — não um contorno desenhado em volta.
ALTURA_BARRA = 20

# O ar entre uma barra e a próxima. Somado à altura, dá a banda de cada
# categoria. Era um 12 literal repetido em dois lugares.
ESPACO_BARRA = 14

# Nas barras agrupadas cada série divide a banda, então a barra é mais fina.
# Proporcionalmente é o mesmo ar: duas de 12 numa banda de 34 por série.
ALTURA_BARRA_AGRUPADA = 12


def _titulo(titulo: str, subtitulo: str | None = None) -> alt.TitleParams:
    return alt.TitleParams(titulo, subtitle=subtitulo or "", anchor="start")


def _tooltips(df: pd.DataFrame, casas: dict[str, int] | None = None) -> tuple[pd.DataFrame, list]:
    """Tooltips com o número **já escrito em português**, como texto.

    O `format` do Vega-Lite é o d3, que formata em inglês, e trocar o locale do
    d3 só é possível pela opção `formatLocale` do vega-embed — que o Streamlit
    descarta (ver `estilo.ROTULO_NUMERO_BR`). Para o eixo dá para contornar com
    expressão; para o tooltip não há gancho equivalente. Então o número sai
    formatado do Python e chega ao tooltip como string.

    Colunas com `_` na frente são de uso interno do gráfico e não viram tooltip.
    """
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


# O Streamlit renderiza com `autosize: fit` — e o `width="stretch"` de cada
# chamada é o que liga isso. Nesse modo a altura pedida é a do gráfico
# **inteiro**: título, subtítulo e eixo x saem de dentro dela, não de fora.
#
# Sem reservar o espaço deles, a banda de cada categoria encolhe até a barra
# encostar na vizinha — foi o que aconteceu com `situacao`, que tem cinco
# categorias: 170px pedidos viravam ~100px de área útil, banda de 20px e barra
# de 20px. Medido renderizando os dois modos com o vl-convert.
ALTURA_MOLDURA = 70


def _altura_fixa(area_de_plotagem: int) -> int:
    """Altura a pedir para obter `area_de_plotagem` de área útil.

    Mesma correção de `_altura`, para os gráficos cuja altura não depende do
    número de categorias: o número escrito na chamada é a área de plotagem
    desejada, e o que se pede ao Vega é ela mais a moldura.
    """
    return area_de_plotagem + ALTURA_MOLDURA


def _altura(categorias: int, por_categoria: int) -> int:
    """Altura fixa a partir do número de categorias.

    O jeito idiomático seria `alt.Step`, que deixa o Vega-Lite dimensionar
    sozinho — mas **`step` não vale em gráfico com camadas**, e todo gráfico daqui
    tem pelo menos duas (a marca e o rótulo). O Vega-Lite não reclama: devolve um
    gráfico vazio. Calcular a altura aqui é feio e é o que funciona.
    """
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
    """Barras horizontais com rótulo direto no fim de cada uma.

    Horizontais porque os rótulos deste projeto são nomes ("Residencial
    unifamiliar", "Serviços especializados para construção") e nome girado 45° é
    o jeito mais rápido de tornar um gráfico ilegível.
    """
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


# Início do eixo logarítmico. A escala precisa dele: os quatro valores vão de
# 2.839 a 887.114 km², e numa escala linear a resposta certa vira um traço
# invisível ao lado da errada.
PISO_LOG_KM2 = 1_000


def decomposicao_log(df: pd.DataFrame, *, titulo: str, subtitulo: str) -> alt.LayerChart:
    """Régua com ponta, em escala logarítmica, com a última linha em azul.

    Não são barras. Barra mede a partir do zero, e o zero não existe em escala
    logarítmica — em Vega-Lite isso não dá erro, dá um gráfico vazio. A régua
    declara de onde parte (`PISO_LOG_KM2`) e o ponto marca onde chega.

    A linha destacada é a **última**, porque a consulta devolve os critérios do
    mais cru ao mais correto. Antes havia uma coluna `ordem` só para dizer isso;
    a ordem das linhas já diz.
    """
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
    """Duas medidas por categoria, na mesma escala e com legenda.

    Só é legítimo quando as duas medidas **são comparáveis** — aqui, duas
    participações percentuais. Duas grandezas diferentes viram dois gráficos.
    """
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
    """Linha com marcador em cada ponto e régua vertical opcional.

    O ponto em cima da linha não é enfeite: sem ele, um ano faltante vira um
    segmento reto e some.
    """
    tabela, dicas = _tooltips(df)
    base = alt.Chart(tabela).encode(
        # `labelExpr` explícito: o tema põe separador de milhar em todo eixo
        # numérico, e ano é a única grandeza deste app que não o quer — 2019
        # viraria "2.019". A exceção fica escrita no eixo que a pede.
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
            # Alinhado à direita, encostando na régua pela esquerda: alinhado à
            # esquerda, um rótulo desses transborda a área do gráfico sempre que a
            # marca cai perto do fim da série — que é justamente o caso aqui.
            alt.Chart(regua)
            .mark_text(align="right", dx=-8, color=estilo.DOURADO, fontSize=11, fontWeight="bold")
            .encode(x=alt.X(f"{x}:O"), y=alt.value(12), text="rotulo:N")
        )
    return alt.layer(*camadas).properties(
        title=_titulo(titulo, subtitulo), height=_altura_fixa(300)
    )


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
    """Bolhas sobre a malha municipal do IBGE.

    Cada bolha é um município, posicionado na **mediana das coordenadas
    plausíveis** das suas obras — não no centroide oficial. É a mesma âncora que a
    curadoria usa para recuperar Plus Code curto, então o mapa mostra o dado que o
    pipeline de fato tem, não uma aproximação cartográfica por cima dele.
    """
    fundo = alt.Chart(alt.Data(values=malha_uf["features"])).mark_geoshape(
        fill=estilo.FUNDO_MAPA, stroke=estilo.GRADE, strokeWidth=0.6
    )
    pontos, dicas = _tooltips(pontos, casas={"area_km2": 2, "latitude": 3, "longitude": 3})
    bolhas = (
        alt.Chart(pontos)
        .mark_circle(
            color=estilo.AZUL,
            # A transparência aqui codifica densidade: onde duas bolhas se
            # sobrepõem o azul acumula. O valor mora em `estilo` porque ele é
            # medido contra o fundo, e o fundo mudou — ver o comentário de
            # `OPACIDADE_BOLHA`.
            opacity=estilo.OPACIDADE_BOLHA,
            # Contorno na cor do fundo: é o que separa duas bolhas encostadas
            # sem gastar uma segunda cor.
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
                # Poucos degraus e dentro do mapa: a legenda padrão do Vega abre
                # oito círculos e rouba um terço da largura do gráfico.
                #
                # `labelExpr` aqui e não no tema: `labelExpr` existe em `Legend`
                # mas **não** em `LegendConfig`, então a versão do tema era
                # config morta — o eixo inteiro saía em português e a legenda do
                # mapa continuava em "1,000". Só a imagem mostrou.
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
    # A projeção vai na camada, nunca em cada sublayer: duas projeções irmãs não
    # se conversam, e o resultado é a malha sumir e os pontos desabarem num
    # amontoado no meio da tela. Centro e escala são calculados a partir da
    # própria malha — ver `malha.enquadramento` para o porquê de não haver ajuste
    # automático aqui.
    centro, escala = malha.enquadramento(malha_uf, largura, altura)
    return (
        alt.layer(fundo, bolhas)
        .project(type="mercator", center=list(centro), scale=escala)
        .properties(title=_titulo(titulo, subtitulo), width=largura, height=altura)
    )
