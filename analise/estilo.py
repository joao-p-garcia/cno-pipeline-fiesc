"""Paleta e estilo dos gráficos, compartilhados pelo notebook e pelo dashboard.

O notebook desenha em matplotlib (a imagem fica salva dentro do `.ipynb`, então o
avaliador lê sem rodar nada) e o dashboard desenha em Altair (interativo). São
duas bibliotecas, mas **uma paleta só** — caso contrário o mesmo achado teria
duas aparências e o leitor pensaria estar vendo duas coisas.

As cores não foram escolhidas no olho. São os três primeiros slots de uma paleta
categórica validada para daltonismo, que é o subconjunto que passa em todos os
pares em modo claro e escuro. As regras que seguimos, e o motivo de cada uma:

* **Série única, cor única.** Barra mais alta não ganha cor mais forte: o
  comprimento já diz o tamanho, e gastar a cor para repetir isso desperdiça o
  único canal livre que sobrou.
* **Ênfase em vez de arco-íris.** Quando o gráfico defende um número, esse número
  fica azul e o resto fica cinza. Oito cores quando a história é uma só é o jeito
  mais comum de um gráfico perder o argumento.
* **Vermelho só para o que está errado.** É cor de estado, não de categoria, e
  nunca aparece sozinha: vem sempre com rótulo.
* **Nunca dois eixos verticais.** Obras e metros quadrados são grandezas
  diferentes; viram dois gráficos, nunca duas escalas no mesmo.
"""

from __future__ import annotations

# Slots categóricos 1 a 3 da paleta de referência. Os três juntos passam nos
# limites de separação sob daltonismo em todos os pares — a partir do quarto slot
# isso deixa de valer, então quatro categorias viram "as três maiores + outras".
AZUL = "#2a78d6"
LARANJA = "#eb6834"
VERDE_AGUA = "#1baf7a"
CATEGORICAS = (AZUL, LARANJA, VERDE_AGUA)

# Estado, não identidade. Só para marcar o que o pipeline descartou ou marcou.
VERMELHO = "#d03b3b"

# Tinta e cromo. Tudo um tom acima da superfície: grade e eixo são hairline e
# recuam; quem tem que aparecer é a marca.
TINTA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
CINZA = "#898781"
GRADE = "#e1e0d9"
SUPERFICIE = "#fcfcfb"

# Terra no mapa: o passo mais claro da mesma rampa azul das bolhas. Recua o
# suficiente para não competir com elas e ainda diz onde é terra e onde não é.
FUNDO_MAPA = "#eaf1fb"

FONTE = ["Segoe UI", "DejaVu Sans", "sans-serif"]

# A mesma pilha, no formato que o Vega-Lite espera: uma string CSS. Precisa ser
# a lista inteira, e não só o primeiro nome — quem renderiza fora do navegador
# (um PNG gerado no Linux, por exemplo) não tem Segoe UI, e uma fonte que não
# existe não cai para a próxima: o texto simplesmente não é desenhado.
FONTE_CSS = ", ".join(FONTE)


def aplicar_matplotlib() -> None:
    """Configura o matplotlib para o estilo do caderno. Chamado uma vez, no topo."""
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "figure.figsize": (9, 4.2),
            "figure.dpi": 110,
            "figure.facecolor": SUPERFICIE,
            "axes.facecolor": SUPERFICIE,
            "axes.edgecolor": GRADE,
            "axes.labelcolor": TINTA_SECUNDARIA,
            "axes.titlecolor": TINTA,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 12,
            "axes.labelsize": 10,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRADE,
            "grid.linewidth": 0.8,
            "xtick.color": CINZA,
            "ytick.color": CINZA,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "text.color": TINTA,
            "font.family": "sans-serif",
            "font.sans-serif": FONTE,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2,
            "lines.markersize": 8,
        }
    )


def enfase(rotulos, destaque) -> list[str]:
    """Azul no que o gráfico defende, cinza no resto.

    `destaque` pode ser um rótulo ou uma coleção deles. É o recurso que substitui
    a paleta de oito cores quando a história é um número só.
    """
    alvos = {destaque} if isinstance(destaque, str) else set(destaque)
    return [AZUL if rotulo in alvos else CINZA for rotulo in rotulos]


def numero(valor: float, casas: int = 0) -> str:
    """Formata no padrão brasileiro: ponto no milhar, vírgula no decimal.

    O Python formata no padrão inglês e nenhum dos dois ambientes (container e
    WSL) tem locale pt-BR instalado. Trocar os separadores à mão é mais confiável
    do que depender de um locale que pode não existir na imagem.
    """
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def percentual(fracao: float, casas: int = 1) -> str:
    """Fração (0 a 1) para texto de porcentagem, com vírgula decimal."""
    return numero(fracao * 100, casas) + "%"


def rotular_barras(
    ax, valores, sufixo: str = "", casas: int = 0, deslocamento: float = 0.01
) -> None:
    """Escreve o valor no fim de cada barra horizontal, em tinta, nunca na cor da série.

    Rótulo direto em vez de grade densa: são poucas barras, e o número exato é
    parte do argumento em quase todos os gráficos deste projeto.
    """
    limite = ax.get_xlim()[1]
    for posicao, valor in enumerate(valores):
        ax.text(
            valor + limite * deslocamento,
            posicao,
            numero(valor, casas) + sufixo,
            va="center",
            fontsize=9,
            color=TINTA_SECUNDARIA,
        )


def registrar_altair() -> None:
    """Registra e ativa o tema do dashboard. Chamado uma vez, na subida do app."""
    import altair as alt

    @alt.theme.register("cno", enable=True)
    def _tema() -> alt.theme.ThemeConfig:
        return {
            "config": {
                "background": SUPERFICIE,
                "font": FONTE_CSS,
                "view": {"stroke": "transparent", "continuousWidth": 640},
                "title": {
                    "color": TINTA,
                    "fontSize": 13,
                    "fontWeight": 600,
                    "anchor": "start",
                    "offset": 12,
                    "subtitleColor": TINTA_SECUNDARIA,
                    "subtitleFontSize": 11,
                },
                "axis": {
                    "labelColor": CINZA,
                    "titleColor": TINTA_SECUNDARIA,
                    "labelFontSize": 11,
                    "titleFontSize": 11,
                    "domainColor": GRADE,
                    "tickColor": GRADE,
                    "gridColor": GRADE,
                    "gridWidth": 0.8,
                    "labelLimit": 220,
                },
                "legend": {
                    "labelColor": TINTA_SECUNDARIA,
                    "titleColor": TINTA_SECUNDARIA,
                    "labelFontSize": 11,
                    "titleFontSize": 11,
                    "symbolType": "square",
                },
                "range": {"category": list(CATEGORICAS)},
                "bar": {"color": AZUL, "cornerRadiusEnd": 3},
                "line": {"color": AZUL, "strokeWidth": 2},
                "point": {"color": AZUL, "size": 70, "filled": True},
            }
        }
