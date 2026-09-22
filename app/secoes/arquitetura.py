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
# a paleta: o tema do app é um só, declarado em `analise/estilo.py`. Herdar a
# tinta da página seria elegante e acrescentaria um fator desconhecido a um
# desenho que já custou duas tentativas para aparecer — ainda mais aqui, onde a
# página é um iframe e não herda quase nada.
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
# sem CSS da página por cima. Custa a herança de tema — de que este app não
# depende, porque todo gráfico já fixa a paleta — e exige altura declarada, daí
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
        "As duas seções anteriores foram uma **análise inicial dos dados e da "
        "extração dos dados**, que motivaram algumas decisões de arquitetura e "
        "stack.",
    )

    ui.diagrama(DIAGRAMA, ALTURA_DIAGRAMA)
    st.caption(
        "Na imagem acima, a arquitetura é representada com fonte de dados (CNO), "
        "orquestração dos dados (Airflow), processamento (DuckDB) e entrega final "
        "(Streamlit que estamos vendo). O repositório também tem CI (Integração "
        "Contínua com Testes), mas o CD seria implementado somente para deploy."
    )

    ui.decisao(
        achado=(
            "A base inteira são **12,5 M de linhas e 1,4 GB de CSV**, que viram ~260 MB em parquet."
        ),
        risco=(
            "Escolher uma ferramenta que trate o problema de forma condizente, sem "
            "over-engineering (Spark pode ser muito pesado ou demais pra uma base de "
            "dados pequenos), mas robusta para pegar inconsistências nos dados e "
            "processar eles em formatos não usuais."
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

    _pandas_ou_polars()

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
            "| **pytest + ruff** | 272 testes offline e 15 das DAGs, mais lint e formatação |\n"
        )
        st.markdown(
            "**Nenhum teste toca a rede.** Eles montam camada sintética e, quando "
            "precisam de HTTP, sobem um servidor local. Assim a CI do GitHub Actions "
            "roda a cada push sem depender de a Receita estar no ar, em Python 3.11 "
            "e 3.12. **CD ainda não existe.** O próximo passo é publicar a imagem "
            "num registry a cada tag."
        )

    ui.rodape(*ui.vizinhos(__name__))


def _pandas_ou_polars() -> None:
    """A medição que decidiu o engine, que é a pergunta mais previsível da seção.

    Fica fora da tabela acima de propósito: as outras quatro linhas se defendem
    com um argumento, esta se defende com três números. Misturar as duas coisas
    na mesma tabela esconderia justamente o que ela tem de mais forte — que a
    escolha foi medida, e não preferida.
    """
    st.markdown("*Comparação de desempenho entre pandas, polars e DuckDB*:")
    st.markdown(
        "| Engine | Tempo | Pico de RAM |\n"
        "|---|---|---|\n"
        "| **DuckDB**, no UTF-8 | **0,8 s** | **457 MB** |\n"
        "| Polars, `windows-1252` | 4,3 s | 2.641 MB |\n"
        "| pandas, `cp1252` | 19,6 s | 4.031 MB |\n"
    )
    st.markdown(
        "*Decisão baseada na RAM utilizada.* "
        "**Quase usei polars**, porque ele lê cp1252 "
        "nativamente, o que eliminaria o passo de transcodificação inteiro. Só que "
        "isso existe apenas na API *eager* , o `scan_csv`, que é a porta da "
        "execução *lazy*, aceita só UTF-8. Para ler cp1252 eu abriria mão do "
        "streaming e a tabela inteira teria de caber na memória."
    )
    st.caption(
        "O DuckDB foi o único dos três que **recusou** o arquivo "
        "declarado como latin-1 com bytes da faixa C1. Os outros dois aceitariam, "
        "então por controle de qualidade de dados deixei o DuckDB."
    )


def _fronteira_externa() -> None:
    """Por que o IBGE não entra no pipeline.

    Está em arquitetura, e não na seção que usa o denominador, porque é decisão
    de fronteira: define o que o pipeline aceita processar. Quem vê o ranking
    por mil habitantes mais adiante precisa saber de onde veio o divisor.
    """
    st.markdown("### IBGE como segunda fonte, mas fora da pipeline")
    st.markdown(
        "Para enriquecer a análise, trouxe dados do IBGE de **população, nome e "
        "região** para dividir obras por habitante e desenhar um mapa. Ela é "
        "gerada por um código separado, versionado, e tem uma DAG própria para "
        "avisar o usuário da validade desses dados.\n\n"
        "O CNO tem uma garantia verificável, fonte versionada por ETag e sha256, "
        "validável utilizando os dados totais publicados, por isso entra na "
        "pipeline e o **IBGE não**. Abaixo outros motivos para o IBGE não entrar "
        "na pipeline mas ter a DAG:"
    )
    st.markdown(
        "- **CSV pode depreciar sozinho** sem avisos.\n"
        "- **População do IBGE e do CNO podem ser de anos diferentes.** Atualizar "
        "sozinho pode quebrar análises ou criar métricas sem sentido. Do jeito "
        "que está hoje, está bem documentado e avisado os anos.\n"
        "- **Não quero colocar DuckDB spatial ou geopandas em produção**, que "
        "pesaria a pipeline, que depende apenas de `requests` e `duckdb`."
    )

    ui.decisao(
        achado=(
            "A Receita identifica município por **TOM de 4 dígitos** e o IBGE por "
            "**código de 7**, sem de-para explícito."
        ),
        risco=(
            "Não quero trazer mais uma tabela para converter esses dados entre si "
            "para ter mais algo para versionar ou entrar na pipeline."
        ),
        decisao=(
            "Juntar por **UF** já resolve **5.555 de 5.572 municípios (99,7%)**. "
            "Os 17 que sobram são o conjunto `PARATI`/`Paraty`, `SANTANA DO "
            "LIVRAMENTO`/`Sant'Ana do Livramento`, `BOA SAÚDE`/`Januário Cicco`, "
            "tem um CSV para corrigir isso no código caso seja necessário. A "
            "segunda DAG, e testes de função no próprio código avisam quando algo "
            "nessa conversão deprecia e o usuário pode alterar."
        ),
    )
