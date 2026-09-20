"""Seção 3 — as escolhas de ferramenta, justificadas pelo que as seções 1 e 2 mediram.

Vem aqui porque é aqui que a pergunta nasce. Depois de ver 12,5 M de linhas em
cp1252 com 1:N, "por que DuckDB?" é pergunta natural; antes disso, seria
currículo. As seções 1 e 2 não são exploração — são o levantamento de
requisitos, e esta seção é a resposta a ele.

**Não confundir com a seção 8.** Esta responde *por que estas ferramentas*; a
seção 8 responde *por que estas fronteiras* — as três camadas e o que cada
achado virou em código. Uma é escolha de tecnologia, a outra é disciplina de
pipeline, e elas se separam bem: o diagrama daqui mostra os processos, o de lá
mostra as camadas.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from analise import estilo

from .. import componentes as ui

TITULO = "Arquitetura e stack"

# O diagrama, com a paleta do resto do app: `estilo.TINTA` na estrutura e
# `estilo.AZUL` reservado para a única coisa que carrega argumento — a fronteira
# de processo entre o Airflow e o pipeline. A Receita fica **fora** da caixa do
# Docker, porque é exatamente isso que ela é: o único pedaço que não
# controlamos.
#
# Cor fixa, e não `currentColor`, pelo mesmo motivo que todo gráfico daqui fixa
# a paleta clara: este app não tem tema escuro. Herdar a tinta da página seria
# elegante e acrescentaria um fator desconhecido a um desenho que já custou duas
# tentativas para aparecer.
#
# **Desenhado num iframe, por `components.html`, e isso é cicatriz.** Três
# tentativas de embutir o SVG direto na página do Streamlit falharam, cada uma
# de um jeito, todas vistas na tela e nenhuma capturada por teste:
#
# 1. `st.markdown(unsafe_allow_html=True)` — markdown fecha um bloco de HTML na
#    primeira linha em branco e trata linha indentada em quatro espaços como
#    bloco de código; um SVG legível tem os dois. Renderizou só a primeira caixa
#    e despejou o resto como parágrafos soltos, um `<text>` por linha.
# 2. `st.html` — sumiu por inteiro. A hipótese era altura colapsada
#    (`width="100%"` com `height:auto` e sem atributos de dimensão).
# 3. `st.html` com `width`/`height` de atributo, `<polygon>` no lugar de
#    `<marker>` e cor fixa em vez de `currentColor` — continuou sumindo. Nesse
#    ponto a hipótese da altura caiu, e o que sobra é o DOMPurify do `st.html`
#    removendo o fragmento.
#
# `components.html` renderiza num iframe: documento próprio, sem sanitizador e
# sem CSS da página por cima. Custa a herança de tema — que este app não usa,
# porque todo gráfico já fixa a paleta clara — e exige altura declarada, daí
# `ALTURA_DIAGRAMA`. Em troca, desenha.
DIAGRAMA = f"""
<svg viewBox="0 0 860 372" role="img" width="860" height="372"
     style="width:100%;max-width:860px;height:auto;display:block;margin:0 0 0.5rem 0;"
     aria-label="A fonte da Receita Federal entra por HTTP num contêiner Docker. Dentro dele o
     Airflow orquestra e invoca o pipeline cno como subprocesso, num venv próprio com DuckDB
     embarcado. O Airflow guarda estado num Postgres que só tem metadados; o pipeline lê e
     escreve arquivos parquet, e o Streamlit lê a camada curada desses arquivos.">

  <g fill="none" stroke="{estilo.TINTA}" stroke-width="1.5">
    <rect x="316" y="10" width="270" height="44" rx="6"/>
  </g>
  <text x="451" y="30" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">Receita Federal</text>
  <text x="451" y="46" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">.zip de 315 MB, republicado sem aviso</text>

  <line x1="451" y1="54" x2="451" y2="96" stroke="{estilo.TINTA}" stroke-width="1.5"/>
  <text x="463" y="80" font-size="11" fill="{estilo.TINTA}" opacity="0.75">
    HTTP · ETag · sha256 por arquivo</text>

  <rect x="16" y="100" width="828" height="256" rx="8" fill="none" stroke="{estilo.TINTA}"
        stroke-width="1.5" stroke-dasharray="5 4" opacity="0.55"/>
  <text x="32" y="122" font-size="11" fill="{estilo.TINTA}" opacity="0.75"
        font-weight="600">Docker — uma imagem, dois ambientes Python</text>

  <g fill="none" stroke="{estilo.TINTA}" stroke-width="1.5">
    <rect x="44" y="140" width="212" height="62" rx="6"/>
    <rect x="44" y="262" width="212" height="62" rx="6"/>
    <rect x="652" y="262" width="176" height="62" rx="6"/>
  </g>
  <rect x="346" y="140" width="240" height="62" rx="6" fill="none" stroke="{estilo.AZUL}"
        stroke-width="2"/>
  <rect x="346" y="262" width="240" height="62" rx="6" fill="none" stroke="{estilo.TINTA}"
        stroke-width="1.5"/>

  <text x="150" y="166" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">Airflow 3.3.2</text>
  <text x="150" y="184" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">LocalExecutor · só orquestra</text>

  <text x="466" y="166" text-anchor="middle" font-size="13" fill="{estilo.AZUL}"
        font-weight="600">cno — venv próprio</text>
  <text x="466" y="184" text-anchor="middle" font-size="11" fill="{estilo.AZUL}"
        opacity="0.85">DuckDB embarcado · faz o trabalho</text>

  <text x="150" y="288" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">Postgres 16</text>
  <text x="150" y="306" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">só metadados da DAG</text>

  <text x="466" y="288" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">parquet em disco</text>
  <text x="466" y="306" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">raw · staging · curated</text>

  <text x="740" y="288" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">Streamlit</text>
  <text x="740" y="306" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">lê a curada, não escreve</text>

  <line x1="256" y1="171" x2="340" y2="171" stroke="{estilo.AZUL}" stroke-width="2"/>
  <text x="298" y="160" text-anchor="middle" font-size="11" fill="{estilo.AZUL}"
        font-weight="600">subprocesso</text>
  <text x="298" y="192" text-anchor="middle" font-size="10" fill="{estilo.AZUL}"
        opacity="0.85">CLI + JSON</text>

  <line x1="150" y1="202" x2="150" y2="256" stroke="{estilo.TINTA}" stroke-width="1.5"/>
  <text x="162" y="234" font-size="11" fill="{estilo.TINTA}" opacity="0.75">estado da DAG</text>

  <line x1="466" y1="202" x2="466" y2="256" stroke="{estilo.AZUL}" stroke-width="2"/>
  <text x="478" y="234" font-size="11" fill="{estilo.AZUL}" opacity="0.85">lê e escreve</text>

  <line x1="586" y1="293" x2="646" y2="293" stroke="{estilo.TINTA}" stroke-width="1.5"/>
  <text x="616" y="283" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">lê</text>
  <!-- Pontas de seta como poligono, e nao <marker>: o st.html sanitiza com
       DOMPurify, e `marker-end` e atributo que ele pode remover. Poligono e
       forma basica, desenha em qualquer lugar. -->
  <polygon points="447,89 455,89 451,96" fill="{estilo.TINTA}"/>
  <polygon points="333,167 333,175 340,171" fill="{estilo.AZUL}"/>
  <polygon points="146,249 154,249 150,256" fill="{estilo.TINTA}"/>
  <polygon points="462,249 470,249 466,256" fill="{estilo.AZUL}"/>
  <polygon points="639,289 639,297 646,293" fill="{estilo.TINTA}"/>
</svg>
"""

# O iframe precisa de altura declarada, e ela não pode ser só os 372 do viewBox:
# a página do iframe tem margem própria. 400 dá folga sem abrir barra de rolagem.
ALTURA_DIAGRAMA = 400

# O documento que vai dentro do iframe. Margem zerada e a mesma superfície do
# app, para a moldura não aparecer como um retângulo branco no meio da página.
PAGINA_DIAGRAMA = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: {estilo.SUPERFICIE}; }}
  body {{ font-family: {estilo.FONTE_CSS}; }}
</style>
</head><body>{DIAGRAMA}</body></html>"""

# O que ficou de fora, e por quê. Dizer não é o que separa decisão de default —
# e cada linha daqui tem um motivo medido, não uma preferência.
NAO_ESCOLHIDOS = [
    {
        "O caminho comum": "Spark ou Dask",
        "Por que não": "12,5 M de linhas e 1,4 GB cabem na memória de uma máquina. Cluster "
        "custaria setup e serialização para uma agregação de 20 s.",
    },
    {
        "O caminho comum": "Data warehouse (BigQuery, Redshift)",
        "Por que não": "Exigiria carga, credencial e custo por consulta para um "
        "dado que o DuckDB lê direto do parquet, sem servidor.",
    },
    {
        "O caminho comum": "Celery + Redis + Flower",
        "Por que não": "Vêm no compose oficial do Airflow. Com LocalExecutor as tasks são "
        "subprocessos do scheduler, e quatro tasks encadeadas não justificam fila "
        "distribuída. Tirei os três serviços.",
    },
    {
        "O caminho comum": "Pipeline importado pela DAG",
        "Por que não": "O Airflow fixa versões de `urllib3`, `requests` e várias outras. Com venv "
        "próprio e chamada por subprocesso, a pipeline sobe de versão sem passar "
        "pelo resolvedor dele.",
    },
]


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "As duas seções anteriores foram o **levantamento de requisitos**. 12,5 M "
        "de linhas que cabem numa máquina, um encoding que engana, uma fonte que "
        "republica sem aviso e quatro tabelas em 1:N. Foi a partir daí que "
        "escolhi as ferramentas, e também o que decidi não usar.",
    )

    components.html(PAGINA_DIAGRAMA, height=ALTURA_DIAGRAMA)
    st.caption(
        "A Receita fica **fora** da caixa porque é a única parte que eu não "
        "controlo. Em azul está a separação entre o Airflow, que orquestra, e a "
        "pipeline, que faz o trabalho: são processos e ambientes Python "
        "diferentes, e conversam por linha de comando e JSON. Vale notar que o "
        "Postgres guarda **só metadados da DAG**, o dado fica em parquet."
    )

    ui.decisao(
        achado=(
            "A base inteira são **12,5 M de linhas e 1,4 GB de CSV**, que viram ~260 MB "
            "em parquet. Cabe com folga na memória de uma máquina comum."
        ),
        risco=(
            "Escolher a ferramenta pelo tamanho que o dado *poderia* ter. Um cluster "
            "Spark aqui custaria configuração, serialização e uma dependência de "
            "infraestrutura para resolver uma agregação por município que o DuckDB "
            "faz em segundos. **Complexidade que não se paga vira custo de "
            "manutenção.**"
        ),
        decisao=(
            "Usei DuckDB embarcado, sem servidor e sem cluster, lendo parquet direto "
            "do disco. A pipeline depende de `duckdb` e `requests` para processar, "
            "e só. A imagem inteira sobe em ~3 min e roda num notebook comum."
        ),
    )

    _fronteira_externa()

    st.markdown("### O que eu não escolhi")
    st.dataframe(pd.DataFrame(NAO_ESCOLHIDOS), hide_index=True, width="stretch")

    with ui.explorar("Ver o stack completo e como ele é verificado"):
        st.markdown(
            "| Peça | Papel |\n"
            "|---|---|\n"
            "| **DuckDB** | todo o processamento: transform, validate e curate, em SQL |\n"
            "| **Parquet** | as camadas staging e curated, particionadas por snapshot |\n"
            "| **Airflow 3.3.2** | duas DAGs: a pipeline diária e a checagem do IBGE |\n"
            "| **Postgres 16** | metadados do Airflow, nada além disso |\n"
            "| **Docker Compose** | a entrega: um comando sobe tudo, em qualquer sistema |\n"
            "| **Streamlit + Altair** | esta apresentação |\n"
            "| **pytest + ruff** | 233 testes offline e 15 das DAGs, mais lint e formatação |\n"
        )
        st.markdown(
            "**Nenhum teste toca a rede.** Eles montam camada sintética e, quando "
            "precisam de HTTP, sobem um servidor local. Assim a CI do GitHub Actions "
            "roda a cada push sem depender de a Receita estar no ar, em Python 3.11 "
            "e 3.12. **CD ainda não existe.** O próximo passo é publicar a imagem "
            "num registry a cada tag."
        )

    ui.rodape(*ui.vizinhos(__name__))


def _fronteira_externa() -> None:
    """Por que o IBGE não entra no pipeline.

    Está em arquitetura, e não na seção que usa o denominador, porque é decisão
    de fronteira: define o que o pipeline aceita processar. Quem vê o ranking
    por mil habitantes mais adiante precisa saber de onde veio o divisor.
    """
    st.markdown("### O dado que vem de fora, e por que ele fica de fora")
    st.markdown(
        "A análise usa **população, nome e região do IBGE** para dividir obras por "
        "habitante e desenhar o mapa. É a segunda fonte do projeto — e ela **não "
        "entra no pipeline**. Entra na análise, como tabela de referência "
        "versionada no repositório.\n\n"
        "O motivo não é purismo. O pipeline tem uma garantia verificável: fonte "
        "versionada por ETag e sha256, reconciliada contra os totais que a própria "
        "Receita publica. **Dado externo não tem nada disso**, e misturar os dois "
        "custa a garantia inteira:"
    )
    st.markdown(
        "- **Proveniência.** CSV commitado envelhece em silêncio.\n"
        "- **Safras misturadas na mesma linha.** Snapshot de 2026 dividido por "
        "população de 2022 não é erro se estiver declarado; é erro grave se não "
        "estiver.\n"
        "- **Cadências diferentes.** A Receita publica de forma irregular, o IBGE "
        "anualmente e com defasagem. Acoplar sincroniza o que não precisa andar "
        "junto.\n"
        "- **Peso do stack.** Geometria pediria DuckDB spatial ou geopandas. Hoje "
        "o pipeline depende de `requests` e `duckdb`, e essa magreza é qualidade."
    )

    ui.decisao(
        achado=(
            "A Receita identifica município por **TOM de 4 dígitos** e o IBGE por "
            "**código de 7**. A de-para entre os dois não vem em nenhuma das duas "
            "fontes — então juntar exige uma ponte."
        ),
        risco=(
            "Importar uma tabela TOM↔IBGE de terceiro parece o caminho curto, mas "
            "troca um problema conhecido por um desconhecido: mais uma fonte sem "
            "proveniência, para resolver um casamento que eu ainda teria de "
            "conferir."
        ),
        decisao=(
            "Junção por **(UF, nome normalizado)**, medida antes de decidir: casa "
            "**5.555 de 5.572 municípios (99,7%)**. Os 17 que sobram são o conjunto "
            "clássico — `PARATI`/`Paraty`, `SANTANA DO LIVRAMENTO`/`Sant'Ana do "
            "Livramento`, `BOA SAÚDE`/`Januário Cicco`, que foi renomeado. Viraram "
            "um CSV de correções auditável linha a linha, com o motivo de cada uma, "
            "e o casamento final é de **5.570 de 5.570**."
        ),
    )

    st.markdown(
        "É também por isso que existe a **segunda DAG**. A `referencias_ibge` roda "
        "mensalmente, não acessa a rede e só verifica se a safra versionada ainda "
        "vale. **Ela pode ficar vermelha sem afetar o pipeline** — que é exatamente "
        "o desacoplamento que a separação das fontes comprou."
    )
