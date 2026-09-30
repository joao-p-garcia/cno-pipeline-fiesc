"""Paleta e estilo dos gráficos, compartilhados pelo notebook e pelo dashboard.

O notebook desenha em matplotlib e o dashboard em Altair, com uma paleta só. As
cores seguem a identidade do Observatório FIESC (tema escuro), e cada escolha
traz o contraste WCAG contra o fundo.

* Série única, cor única.
* Ênfase em vez de arco-íris: o número defendido fica azul, o resto cinza.
* Vermelho só para o que está errado, e sempre com rótulo.
* Nunca dois eixos verticais.
"""

from __future__ import annotations

from pathlib import Path

# --- Superfícies -----------------------------------------------------------
# Diferença de 1,26:1 entre as duas, para a superfície não disputar com o dado.
SUPERFICIE = "#1e1e29"  # Nanquim
SUPERFICIE_ELEVADA = "#2e303d"  # Chumbo

# --- Tinta e cromo ---------------------------------------------------------
# Contraste contra Nanquim: Gelo 15,1:1, Nublado 11,1:1, Pedra 7,3:1, Granito 2,2:1.
TINTA = "#f4f5f9"  # Gelo
TINTA_SECUNDARIA = "#cbd5df"  # Nublado
CINZA = "#a1aebf"  # Pedra
GRADE = "#4a5567"  # Granito

# --- Cor do dado -----------------------------------------------------------
# O azul da marca mede 3,96:1 sobre Nanquim, pouco para linha fina e rótulo.
# As séries usam Azul piscina (8,6:1), e AZUL_MARCA fica para o chrome.
AZUL = "#6bc4fe"  # Azul piscina
AZUL_MARCA = "#0077fc"  # Azul Observatório

# Separação contra o azul em normal/deuteranopia/protanopia: 81/66/61.
DOURADO = "#ffdf6f"

# O trio tem 31,7 no pior par sob daltonismo.
CEREJA = "#ff7171"

# A partir do quarto slot a separação sob daltonismo deixa de valer.
CATEGORICAS = (AZUL, DOURADO, CEREJA)

FUNDO_MAPA = SUPERFICIE_ELEVADA

# A 0,65 a bolha dá 4,42:1 e duas sobrepostas ainda se distinguem.
OPACIDADE_BOLHA = 0.65

# --- Tipografia ------------------------------------------------------------
FONTE = ["Montserrat", "Segoe UI", "DejaVu Sans", "sans-serif"]
FONTE_MIUDA = ["Open Sans", "Segoe UI", "DejaVu Sans", "sans-serif"]

# `woff2` para o navegador e `ttf` para o matplotlib, gerados do mesmo arquivo
# (ver `app/static/fontes/README.md`). Os `.ttf` são instâncias estáticas 400 e
# 600, porque a fonte variável cairia no peso padrão Thin dentro do matplotlib.
DIR_FONTES = Path(__file__).resolve().parents[1] / "app" / "static" / "fontes"

# A pilha inteira, porque o Vega não cai para a próxima fonte se a primeira faltar.
FONTE_CSS = ", ".join(FONTE)
FONTE_MIUDA_CSS = ", ".join(FONTE_MIUDA)


def _registrar_fontes_no_matplotlib() -> None:
    """Registra no matplotlib as fontes que estão no repositório.

    Sem isso o caderno depende das fontes instaladas na máquina e o matplotlib
    troca de fonte sem avisar.
    """
    from matplotlib import font_manager

    for arquivo in sorted(DIR_FONTES.glob("*.ttf")):
        font_manager.fontManager.addfont(str(arquivo))


def aplicar_matplotlib() -> None:
    """Configura o matplotlib para o estilo do caderno. Chamado uma vez, no topo."""
    import matplotlib as mpl

    _registrar_fontes_no_matplotlib()

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
            "axes.titleweight": 600,
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
            # Sem isso o PNG sai com fundo branco em volta dos eixos.
            "savefig.facecolor": SUPERFICIE,
            "savefig.edgecolor": SUPERFICIE,
        }
    )


def tinta_sobre(cor: str) -> str:
    """Devolve `SUPERFICIE` ou `TINTA`, o que tiver mais contraste contra `cor`."""

    def luminancia(hexa: str) -> float:
        canais = (int(hexa.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canais)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contraste(a: str, b: str) -> float:
        claro, escuro = sorted((luminancia(a), luminancia(b)), reverse=True)
        return (claro + 0.05) / (escuro + 0.05)

    return max((SUPERFICIE, TINTA), key=lambda tinta: contraste(tinta, cor))


def enfase(rotulos, destaque) -> list[str]:
    """Azul no que o gráfico defende, cinza no resto. `destaque` é um rótulo ou vários."""
    alvos = {destaque} if isinstance(destaque, str) else set(destaque)
    return [AZUL if rotulo in alvos else CINZA for rotulo in rotulos]


def numero(valor: float, casas: int = 0) -> str:
    """Formata no padrão brasileiro, sem depender de locale pt-BR instalado."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def percentual(fracao: float, casas: int = 1) -> str:
    """Fração (0 a 1) para texto de porcentagem, com vírgula decimal."""
    return numero(fracao * 100, casas) + "%"


# A mesma troca de `numero`, como expressão Vega, para os rótulos de eixo. O
# `formatLocale` do vega-embed não serve porque o Streamlit descarta
# `usermeta.embedOptions`. Sem o `/g` só a primeira ocorrência é trocada.
ROTULO_NUMERO_BR = (
    "isNumber(datum.value)"
    r" ? replace(replace(replace(format(datum.value, ','), /,/g, '~'), /\./g, ','),"
    " /~/g, '.')"
    " : datum.label"
)

# Para eixo de ano, que sairia como "2.019" com o separador.
ROTULO_SEM_SEPARADOR = "datum.label"


def rotular_barras(
    ax, valores, sufixo: str = "", casas: int = 0, deslocamento: float = 0.01
) -> None:
    """Escreve o valor no fim de cada barra horizontal."""
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


def tema_altair() -> dict:
    """O tema do dashboard, como dicionário, para poder ser lido sem ser aplicado."""
    return {
        "config": {
            "background": SUPERFICIE,
            "font": FONTE_CSS,
            "view": {"stroke": "transparent", "continuousWidth": 640},
            "title": {
                "color": TINTA,
                "font": FONTE_CSS,
                "fontSize": 13,
                "fontWeight": 600,
                "anchor": "start",
                "offset": 12,
                "subtitleColor": TINTA_SECUNDARIA,
                "subtitleFont": FONTE_MIUDA_CSS,
                "subtitleFontSize": 11,
            },
            "axis": {
                "labelColor": CINZA,
                "titleColor": TINTA_SECUNDARIA,
                "labelFont": FONTE_MIUDA_CSS,
                "titleFont": FONTE_MIUDA_CSS,
                "labelFontSize": 11,
                "titleFontSize": 11,
                "domainColor": GRADE,
                "tickColor": GRADE,
                "gridColor": GRADE,
                "gridWidth": 0.8,
                "labelLimit": 220,
                "labelExpr": ROTULO_NUMERO_BR,
            },
            "legend": {
                "labelColor": TINTA_SECUNDARIA,
                "titleColor": TINTA_SECUNDARIA,
                "labelFont": FONTE_MIUDA_CSS,
                "titleFont": FONTE_MIUDA_CSS,
                "labelFontSize": 11,
                "titleFontSize": 11,
                "symbolType": "square",
                # `labelExpr` não existe em `LegendConfig`; vai no encoding.
            },
            "range": {"category": list(CATEGORICAS)},
            "bar": {"color": AZUL, "cornerRadiusEnd": 3},
            "line": {"color": AZUL, "strokeWidth": 2},
            "point": {"color": AZUL, "size": 70, "filled": True},
            "text": {"color": TINTA_SECUNDARIA, "font": FONTE_MIUDA_CSS},
        }
    }


def registrar_altair() -> None:
    """Registra e ativa o tema do dashboard. Chamado uma vez, na subida do app."""
    import altair as alt

    alt.theme.register("cno", enable=True)(tema_altair)
