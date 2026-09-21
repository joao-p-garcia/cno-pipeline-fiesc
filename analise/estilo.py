"""Paleta e estilo dos gráficos, compartilhados pelo notebook e pelo dashboard.

O notebook desenha em matplotlib (a imagem fica salva dentro do `.ipynb`, então o
avaliador lê sem rodar nada) e o dashboard desenha em Altair (interativo). São
duas bibliotecas, mas **uma paleta só** — caso contrário o mesmo achado teria
duas aparências e o leitor pensaria estar vendo duas coisas.

As cores saem do brandbook do Observatório FIESC (2025), e o tema é **escuro**,
que é a superfície dominante do brandbook. O que este módulo acrescenta ao
brandbook é a medição: uma paleta de slide pode se dar ao luxo de ser toda azul,
um gráfico não, porque ali a cor é o dado. Cada escolha abaixo traz o contraste
WCAG contra o fundo e, quando separa categorias, a distância entre as cores
simulada sob deuteranopia e protanopia.

As regras que seguimos, e o motivo de cada uma:

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

from pathlib import Path

# --- Superfícies -----------------------------------------------------------
# Nanquim é o fundo dos slides escuros do brandbook, e é o fundo do app. Chumbo
# é o degrau acima: cartão, expander, e a terra no mapa. A diferença entre os
# dois é 1,26:1 — de propósito. Superfície que disputa atenção com o dado é
# ruído com aparência de organização.
SUPERFICIE = "#1e1e29"  # Nanquim
SUPERFICIE_ELEVADA = "#2e303d"  # Chumbo

# --- Tinta e cromo ---------------------------------------------------------
# Contraste contra Nanquim: Gelo 15,1:1, Nublado 11,1:1, Pedra 7,3:1. A grade é
# Granito a 2,2:1, e o número baixo é a intenção: hairline recua, marca aparece.
TINTA = "#f4f5f9"  # Gelo
TINTA_SECUNDARIA = "#cbd5df"  # Nublado
CINZA = "#a1aebf"  # Pedra — o "resto" quando um número ganha ênfase
GRADE = "#4a5567"  # Granito

# --- Cor do dado -----------------------------------------------------------
# **Azul piscina, e não Azul Observatório, é a cor das séries.** O azul da marca
# (#0077fc) mede 3,96:1 sobre Nanquim: suficiente para uma área grande, fraco
# para linha de 2px, ponto de dispersão e texto de rótulo — que é onde este app
# gasta azul. Azul piscina é da mesma família e mede 8,6:1. O azul da marca
# continua existindo, em AZUL_MARCA, onde o papel é identidade e não leitura:
# widget, link, foco — o chrome do Streamlit.
AZUL = "#6bc4fe"  # Azul piscina — série, ênfase, bolha do mapa
AZUL_MARCA = "#0077fc"  # Azul Observatório — identidade, nunca dado

# Dourado é o segundo slot: mediana, linha de referência, a anotação que
# contrasta com a série. Separação contra o azul, em normal/deuteranopia/
# protanopia: 81/66/61. O par que este tema substitui (azul #2a78d6 + laranja
# #eb6834) media 99/79/67 — cai um pouco e segue muito acima do limite.
DOURADO = "#ffdf6f"

# Terceiro slot. O trio inteiro tem 31,7 no pior par sob daltonismo, contra 31,5
# do trio anterior: empata. Cereja é vermelho, e a regra acima reserva vermelho
# para estado — a reserva vale onde ela importa, que é o vermelho **sozinho**
# marcando erro, e hoje nenhum gráfico deste app faz isso. Se algum passar a
# fazer, este slot sai da categoria antes de o vermelho virar ambíguo.
CEREJA = "#ff7171"

# A partir do quarto slot a separação sob daltonismo deixa de valer, então quatro
# categorias viram "as três maiores + outras".
CATEGORICAS = (AZUL, DOURADO, CEREJA)

# Terra no mapa: o mesmo degrau de superfície dos cartões. Recua o suficiente
# para não competir com as bolhas e ainda diz onde é terra e onde não é.
FUNDO_MAPA = SUPERFICIE_ELEVADA

# Opacidade das bolhas do mapa. Não é gosto: a 0,55 sobre fundo escuro a bolha
# cai para 3,54:1 e some; a 0,65 ela dá 4,42:1, e duas bolhas sobrepostas ainda
# se distinguem uma da outra (distância 25), que é a única razão de a
# transparência existir aqui — ela codifica densidade. No tema claro anterior
# esse mesmo ponto media 2,12:1: o mapa escuro lê melhor, não pior.
OPACIDADE_BOLHA = 0.65

# --- Tipografia ------------------------------------------------------------
# Montserrat é a fonte primária do brandbook (títulos e corpo); Open Sans é a
# secundária, para subtítulo e texto pequeno — que num gráfico é rótulo de eixo
# e legenda. As duas vêm empacotadas no repositório, e não de CDN: numa
# apresentação ao vivo, fonte que depende de rede é fonte que pode não chegar.
FONTE = ["Montserrat", "Segoe UI", "DejaVu Sans", "sans-serif"]
FONTE_MIUDA = ["Open Sans", "Segoe UI", "DejaVu Sans", "sans-serif"]

# **Por que as fontes moram debaixo de `app/`, se este módulo também as usa.**
# Porque o Streamlit só serve arquivo estático de uma pasta `static/` ao lado do
# entrypoint — não é escolha de arquitetura, é o que a ferramenta aceita. Este
# módulo alcança a pasta por caminho, não por import, então a dependência
# continua indo numa direção só: `app` conhece `analise`, nunca o contrário.
#
# Dois formatos, cada um com o seu consumidor: `woff2` é o que o navegador
# carrega (dashboard) e `ttf` é o que o matplotlib lê (caderno). Os `.ttf` foram
# gerados a partir do `.woff2`, então têm exatamente o mesmo conjunto de glifos —
# o caderno não desenha um caractere que o app não desenha. Como refazer está em
# `app/static/fontes/README.md`.
#
# **E os `.ttf` são instâncias estáticas, não a fonte variável.** O Montserrat do
# Google é variável com padrão em `wght=100`: o navegador nunca vê isso, porque
# o CSS pede o peso que quer, mas o matplotlib lê a instância padrão e pronto.
# Registrada a variável direto, o caderno inteiro sairia em Thin — cinza-claro,
# fino, sobre fundo escuro, sem erro nenhum no caminho. Daí dois arquivos, 400 e
# 600, com `nameID 1` forçado para "Montserrat" nos dois: é por esse nome que o
# matplotlib agrupa família, e "Montserrat SemiBold" seria uma família à parte.
DIR_FONTES = Path(__file__).resolve().parents[1] / "app" / "static" / "fontes"

# A mesma pilha, no formato que o Vega-Lite espera: uma string CSS. Precisa ser
# a lista inteira, e não só o primeiro nome — quem renderiza fora do navegador
# (um PNG gerado no Linux, por exemplo) não tem Montserrat instalada se a imagem
# não a instalar, e uma fonte que não existe não cai para a próxima: o texto
# simplesmente não é desenhado.
FONTE_CSS = ", ".join(FONTE)
FONTE_MIUDA_CSS = ", ".join(FONTE_MIUDA)


def _registrar_fontes_no_matplotlib() -> None:
    """Ensina o matplotlib a achar as fontes da marca que viajam no repositório.

    Sem isto, o caderno dependeria de as fontes estarem **instaladas na máquina
    de quem executa** — e o modo de falhar é o pior possível: o matplotlib não
    ergue erro, escolhe a próxima da pilha e grava o PNG. Duas pessoas rodando o
    mesmo notebook commitariam figuras com tipografias diferentes, e o diff não
    diria o porquê.

    Silencioso quando o arquivo não existe, de propósito: a pilha de `FONTE` já
    tem substituto declarado, e um caderno que se recusa a rodar por causa de
    fonte trocaria um problema cosmético por um impeditivo.
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
            # O PNG salvo dentro do `.ipynb` carrega o próprio fundo. O default
            # do matplotlib é gravar com fundo branco, ignorando o da figura —
            # e aí a figura escura sairia com um halo claro em volta dos eixos.
            "savefig.facecolor": SUPERFICIE,
            "savefig.edgecolor": SUPERFICIE,
        }
    )


def tinta_sobre(cor: str) -> str:
    """A tinta legível para escrever **em cima** de uma marca preenchida.

    Rótulo dentro da barra é o único lugar do tema onde a cor do texto não pode
    ser fixa: ela depende do que está embaixo. Num tema claro a resposta é quase
    sempre branco; num escuro, quase sempre o contrário — e é exatamente por ser
    "quase sempre" que a conta vale mais do que a intuição. A barra azul deste
    app é clara (Azul piscina), a barra cinza é escura (Granito), e as duas
    aparecem lado a lado no mesmo gráfico.

    Devolve `SUPERFICIE` ou `TINTA`, o que tiver mais contraste contra a marca.
    """

    def luminancia(hexa: str) -> float:
        canais = (int(hexa.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canais)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contraste(a: str, b: str) -> float:
        claro, escuro = sorted((luminancia(a), luminancia(b)), reverse=True)
        return (claro + 0.05) / (escuro + 0.05)

    return max((SUPERFICIE, TINTA), key=lambda tinta: contraste(tinta, cor))


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


# A mesma troca de `numero`, escrita como expressão Vega, para os rótulos de
# eixo - que são formatados no navegador, não em Python.
#
# **Por que não é o `formatLocale` do vega-embed.** Era, e não funcionava.
# Aquela opção viaja em `usermeta.embedOptions`, e o Streamlit (1.64) filtra
# esse objeto: mantém `theme`, `renderer` e `padding` e descarta o resto. O
# carimbo saía do Python e morria no frontend - todo eixo do dashboard vinha
# com vírgula de milhar, e nada acusava. Expressão é parte do spec, e spec
# ninguém filtra.
#
# O `/g` não é detalhe: sem ele o `replace` do Vega troca só a primeira
# ocorrência, e 1.000.000 sai como "1.000,000" - medido, renderizando. O `~`
# é o pivô que impede a segunda troca de desfazer a primeira, como o
# caractere nulo em `numero`; não aparece em número formatado.
ROTULO_NUMERO_BR = (
    "isNumber(datum.value)"
    r" ? replace(replace(replace(format(datum.value, ','), /,/g, '~'), /\./g, ','),"
    " /~/g, '.')"
    " : datum.label"
)

# Eixo de ano opta por sair: `format(2019, ',')` devolveria "2.019". Quem
# desenha um eixo de ano usa isto no lugar do default do tema.
ROTULO_SEM_SEPARADOR = "datum.label"


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


def tema_altair() -> dict:
    """O tema do dashboard, como dicionário.

    Função de módulo, e não closure dentro de `registrar_altair`, para que possa
    ser **lido sem ser aplicado**: há teste que confere que o eixo numérico
    carrega a formatação brasileira, e um tema preso dentro do decorador só
    existiria depois do efeito colateral de registrá-lo.
    """
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
                # Open Sans no miúdo, como manda o brandbook: Montserrat é fonte
                # de título, e num rótulo de 11px ela fecha demais a contraforma.
                "labelFont": FONTE_MIUDA_CSS,
                "titleFont": FONTE_MIUDA_CSS,
                "labelFontSize": 11,
                "titleFontSize": 11,
                "domainColor": GRADE,
                "tickColor": GRADE,
                "gridColor": GRADE,
                "gridWidth": 0.8,
                "labelLimit": 220,
                # Vale para todo eixo numérico do app. Ano é a exceção, e cada
                # eixo de ano a declara — ver `ROTULO_SEM_SEPARADOR`.
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
                # `labelExpr` **não** entra aqui: existe em `Legend`, não em
                # `LegendConfig`, e no tema seria config morta. Quem tem legenda
                # numérica declara no próprio encoding — ver `graficos.mapa`.
            },
            "range": {"category": list(CATEGORICAS)},
            "bar": {"color": AZUL, "cornerRadiusEnd": 3},
            "line": {"color": AZUL, "strokeWidth": 2},
            "point": {"color": AZUL, "size": 70, "filled": True},
            # Texto solto num gráfico (rótulo de barra, anotação) herda daqui.
            # Sem isto ele nasce preto, que sobre Nanquim é quase invisível — e
            # o rótulo é parte do argumento em quase todo gráfico deste projeto.
            "text": {"color": TINTA_SECUNDARIA, "font": FONTE_MIUDA_CSS},
        }
    }


def registrar_altair() -> None:
    """Registra e ativa o tema do dashboard. Chamado uma vez, na subida do app."""
    import altair as alt

    alt.theme.register("cno", enable=True)(tema_altair)
