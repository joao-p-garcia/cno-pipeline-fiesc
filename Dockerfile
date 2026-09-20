# syntax=docker/dockerfile:1

# Uma imagem só, carregando os dois lados da entrega: o Airflow que orquestra e
# o pipeline que faz o trabalho. Eles dividem o sistema de arquivos, mas não as
# dependências — o pipeline mora num venv próprio em /opt/cno/.venv e a DAG o
# invoca por caminho absoluto (CNO_BIN). É a mesma fronteira de processo que já
# existe em desenvolvimento, agora empacotada: o pipeline pode subir de versão
# sem passar pelo resolvedor de dependências do Airflow, que é rígido por
# necessidade (ele fixa versões de urllib3, requests e mais meia dúzia).
ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:${AIRFLOW_VERSION}

# /opt/cno/data é criado aqui, com dono `airflow`, de propósito: um volume
# nomeado herda dono e permissões do diretório que a imagem já traz no ponto de
# montagem. Sem isso o Docker criaria a montagem como root e o pipeline não
# conseguiria escrever. É também por isso que este compose não precisa de
# AIRFLOW_UID nem de um init que sai fazendo chown -R, como faz o oficial.
USER root
RUN install -d -o airflow -g root -m 775 /opt/cno /opt/cno/data
USER airflow

RUN python -m venv /opt/cno/.venv \
    && /opt/cno/.venv/bin/pip install --no-cache-dir --upgrade pip

# Instalado de verdade, não em modo editável: a imagem é um artefato de entrega,
# e `pip install -e` deixaria o código dependendo de um diretório de fontes que
# só existe por acidente de build.
COPY --chown=airflow:root pyproject.toml /opt/cno/pacote/pyproject.toml
COPY --chown=airflow:root src /opt/cno/pacote/src
RUN /opt/cno/.venv/bin/pip install --no-cache-dir /opt/cno/pacote

# A DAG vai embutida na imagem em vez de montada do host. Assim `docker compose
# up` funciona a partir de um clone recém-feito, sem bind mount, sem ajuste de
# UID e sem o risco de o scheduler enxergar uma versão da DAG diferente da que o
# dag-processor leu. Em troca, mexer na DAG exige `make build` — o que combina
# com o papel do container aqui, que é empacotar a entrega, não desenvolver.
COPY --chown=airflow:root dags/ /opt/airflow/dags/

# O caminho do executável é o contrato entre a DAG e o pipeline. Fica no
# ENV da imagem para valer também em `docker run` direto, sem compose.
# O PATH de propósito NÃO recebe /opt/cno/.venv/bin: isso trocaria o `python`
# visto pelo Airflow pelo do venv do pipeline, que não tem Airflow dentro.
ENV CNO_BIN=/opt/cno/.venv/bin/cno \
    CNO_DATA_DIR=/opt/cno/data
