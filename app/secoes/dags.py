"""Seção 4 — a orquestração: quando roda, em que ordem, e o que acontece quando falha.

Existe por dois motivos, e o segundo é de narrativa.

**O primeiro:** a apresentação falava do Airflow como escolha de ferramenta
(seção 3) e das camadas como disciplina de dados (seção 9), mas em nenhum lugar
dizia o óbvio — que horas a pipeline roda, quais são as tarefas, o que acontece
quando uma falha. Quem assiste precisa disso para acreditar que o sistema roda
sozinho.

**O segundo:** as seções 1 a 3 constroem, as seções 5 a 8 analisam. Essa troca
de gênero precisava de uma dobradiça. É esta seção: o momento em que o trabalho
deixa de ser mover dado e passa a ser olhar para ele — porque a máquina passou a
fazer a primeira parte sozinha, todo dia às quatro da manhã.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analise import estilo

from .. import componentes as ui

TITULO = "As duas DAGs"

# Mesmo tratamento do diagrama da seção 3, pelas mesmas cicatrizes: iframe via
# `components.html`, cor fixa e setas em `<polygon>`. O porquê de cada uma está
# documentado em `arquitetura.py` — três tentativas de embutir SVG direto na
# página do Streamlit falharam antes de o iframe funcionar.
ALTURA_DIAGRAMA = 330

# Apelido curto porque a cor aparece sete vezes no SVG abaixo, e `{estilo.DOURADO}`
# repetido dentro da f-string esconde o desenho.
_DOURADO = estilo.DOURADO

DIAGRAMA = f"""
<svg viewBox="0 0 860 296" role="img" width="860" height="296"
     style="width:100%;max-width:860px;height:auto;display:block;"
     aria-label="A DAG cno_pipeline encadeia quatro tarefas — extrair, tratar, validar e curar.
     A extração tem três tentativas com backoff. A validação é um portão: se reprovar, a
     curadoria não roda. Uma segunda DAG, referencias_ibge, roda mensalmente, não acessa a rede
     e falha quando a safra do IBGE vence, sem afetar a pipeline principal.">
  <text x="20" y="22" font-size="12" fill="{estilo.TINTA}" font-weight="600">
    cno_pipeline — diária às 04:00 (0 4 * * *) · sem catchup · uma execução por vez</text>
  <g fill="none" stroke="{estilo.TINTA}" stroke-width="1.5">
    <rect x="45" y="48" width="170" height="56" rx="6"/>
    <rect x="245" y="48" width="170" height="56" rx="6"/>
    <rect x="645" y="48" width="170" height="56" rx="6"/>
  </g>
  <rect x="445" y="48" width="170" height="56" rx="6" fill="none" stroke="{_DOURADO}"
        stroke-width="2"/>
  <text x="130" y="72" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">extrair</text>
  <text x="130" y="90" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">zip da Receita → raw</text>
  <text x="330" y="72" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">tratar</text>
  <text x="330" y="90" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">raw → staging, em parquet</text>
  <text x="530" y="72" text-anchor="middle" font-size="13" fill="{_DOURADO}"
        font-weight="600">validar</text>
  <text x="530" y="90" text-anchor="middle" font-size="11" fill="{_DOURADO}"
        opacity="0.85">19 regras + reconciliação</text>
  <text x="730" y="72" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">curar</text>
  <text x="730" y="90" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">analítica + 3 marts</text>
  <line x1="215" y1="76" x2="238" y2="76" stroke="{estilo.TINTA}" stroke-width="1.5"/>
  <polygon points="238,72 238,80 245,76" fill="{estilo.TINTA}"/>
  <line x1="415" y1="76" x2="438" y2="76" stroke="{estilo.TINTA}" stroke-width="1.5"/>
  <polygon points="438,72 438,80 445,76" fill="{estilo.TINTA}"/>
  <line x1="615" y1="76" x2="638" y2="76" stroke="{_DOURADO}" stroke-width="2"/>
  <polygon points="638,72 638,80 645,76" fill="{_DOURADO}"/>
  <text x="130" y="126" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">3 tentativas · backoff · retoma o download</text>
  <text x="330" y="126" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">sem retry: é determinístico</text>
  <text x="628" y="126" text-anchor="middle" font-size="11" fill="{_DOURADO}"
        font-weight="600">reprovou aqui → curar não roda</text>
  <text x="430" y="158" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">o mesmo snapshot_id atravessa as quatro tarefas</text>
  <line x1="20" y1="188" x2="840" y2="188" stroke="{estilo.TINTA}" stroke-width="1"
        stroke-dasharray="4 4" opacity="0.3"/>
  <text x="20" y="216" font-size="12" fill="{estilo.TINTA}" font-weight="600">
    referencias_ibge — mensal (@monthly) · não acessa a rede</text>
  <rect x="45" y="232" width="330" height="48" rx="6" fill="none" stroke="{estilo.TINTA}"
        stroke-width="1.5"/>
  <text x="210" y="252" text-anchor="middle" font-size="13" fill="{estilo.TINTA}"
        font-weight="600">verificar_validade</text>
  <text x="210" y="269" text-anchor="middle" font-size="11" fill="{estilo.TINTA}"
        opacity="0.75">falha quando a safra do IBGE vence</text>
  <text x="405" y="252" font-size="11" fill="{estilo.TINTA}" opacity="0.75">
    DAG separada de propósito: pode ficar vermelha o tempo que for</text>
  <text x="405" y="269" font-size="11" fill="{estilo.TINTA}" opacity="0.75">
    sem afetar a pipeline acima, o aviso é sobre a análise, não sobre o dado</text>
</svg>
"""


# Retry é decisão, não default. Cada linha diz por que aquela política.
POLITICA = [
    {
        "Tarefa": "extrair",
        "Retry": "3, com backoff exponencial",
        "Por quê": "é a única etapa que depende de rede, e o download é resumível, "
        "então uma nova tentativa continua de onde parou",
    },
    {
        "Tarefa": "tratar",
        "Retry": "nenhum",
        "Por quê": "determinística: se falhou, falha de novo. Retry só atrasaria o erro",
    },
    {
        "Tarefa": "validar",
        "Retry": "nenhum",
        "Por quê": "reprovação não é instabilidade, é diagnóstico. Tentar de novo dá o mesmo "
        "resultado",
    },
    {
        "Tarefa": "curar",
        "Retry": "nenhum",
        "Por quê": "determinística, e só chega aqui quem passou pela validação",
    },
]


def render() -> None:
    ui.cabecalho()
    ui.titulo(
        ui.posicao(__name__),
        TITULO,
        "São duas DAGs separadas. A de cima roda a pipeline todo dia de madrugada "
        "e a de baixo só verifica se a tabela do IBGE ainda está válida. **Separei "
        "as duas para a segunda poder falhar sem derrubar a primeira.**",
    )

    ui.diagrama(DIAGRAMA, ALTURA_DIAGRAMA)
    st.caption(
        "O `snapshot_id` sai da extração e passa pelas outras três tarefas. Cada "
        "uma recebe **qual** snapshot processar, pra não quebrar a DAG caso a "
        "Receita publique novos dados enquanto a pipeline é processada."
    )

    ui.decisao(
        achado=(
            "O dado curado é o final e alimenta o Streamlit. Roda logo depois da "
            "validação, que confere 19 regras e reconcilia as contagens com os "
            "totais da CNO."
        ),
        risco=(
            "Curar antes de validar, ou validar e seguir mesmo assim, e fazer o "
            "Streamlit exibir dados errados."
        ),
        decisao=(
            "A validação bloqueia: reprovar **derruba a execução** e o `curar` não "
            "roda. A camada curada do dia anterior continua servindo o Streamlit e "
            "o alerta do Airflow avisa que mudou algo na fonte."
        ),
    )

    with ui.explorar("Ver a política de retry, tarefa por tarefa"):
        st.dataframe(pd.DataFrame(POLITICA), hide_index=True, width="stretch")
        st.markdown(
            "**Por que `catchup=False`.** A fonte expõe só a publicação corrente, sem "
            "histórico, então não existe backfill possível. Ligar isso só produziria "
            "N execuções do mesmo dado.\n\n"
            "**Por que `max_active_runs=1`.** Duas execuções simultâneas disputariam "
            "os mesmos diretórios. Tem também um lock por snapshot dentro do `transform` "
            "e do `curate`, para o caso de alguém rodar a CLI à mão enquanto a DAG "
            "roda.\n\n"
            "**Por que o Triggerer aparece vermelho na UI do Airflow.** Ele não existe "
            "nesta stack. Nenhuma tarefa daqui é *deferrable* (adiável), então tirei o "
            "serviço do compose junto com o Redis, o worker Celery e o Flower."
        )

    st.markdown(
        "---\n\n"
        "Com a pipeline rodando todo dia o Streamlit é feito e é possível seguir "
        "a análise."
    )

    ui.rodape(*ui.vizinhos(__name__))