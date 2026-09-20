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
#
# O extra `dashboard` entra aqui, e só ele: são o Streamlit, o pandas e o
# Altair, que o app importa. O extra `notebook` (Jupyter, matplotlib) fica de
# fora de propósito — o caderno é registro de como os achados surgiram, não
# serviço, e não há por que carregar JupyterLab numa imagem de produção.
COPY --chown=airflow:root pyproject.toml /opt/cno/pacote/pyproject.toml
COPY --chown=airflow:root src /opt/cno/pacote/src
RUN /opt/cno/.venv/bin/pip install --no-cache-dir "/opt/cno/pacote[dashboard]"

# Fumaça em tempo de build, não em tempo de DAG.
#
# Existe porque dependência declarada só implicitamente passa em toda a suíte de
# testes da máquina de quem desenvolve e quebra no primeiro venv limpo. Já
# aconteceu neste projeto: o `create_function` do DuckDB exigia numpy, o venv
# local tinha numpy de carona e o do container não, e o erro só apareceu quando a
# task falhou dentro do Airflow. A UDF saiu, mas a lição fica — um segundo de
# build move essa classe de falha para onde ela é barata de ver.
RUN /opt/cno/.venv/bin/python -c "from cno_pipeline.curate.geocodificacao import decodificar; lat, lon = decodificar('584FPC38+X8'); assert -27.4 < lat < -27.2 and -50.7 < lon < -50.5, (lat, lon); print('geocodificação responde no ambiente da imagem')"

# A DAG vai embutida na imagem em vez de montada do host. Assim `docker compose
# up` funciona a partir de um clone recém-feito, sem bind mount, sem ajuste de
# UID e sem o risco de o scheduler enxergar uma versão da DAG diferente da que o
# dag-processor leu. Em troca, mexer na DAG exige `make build` — o que combina
# com o papel do container aqui, que é empacotar a entrega, não desenvolver.
COPY --chown=airflow:root dags/ /opt/airflow/dags/

# A camada de análise — tabela de referência do IBGE e a ponte que a junta com a
# camada curada. Não é parte do pipeline (o `cno` não a importa), mas precisa
# existir na imagem por três motivos: a DAG `referencias_ibge` lê a validade da
# safra da população, o dashboard lê a tabela em execução, e as consultas de
# `analise/dados.py` são as mesmas que o notebook usa.
#
# O notebook em si não entra na imagem (está no `.dockerignore`): são 630 KB de
# saídas que ninguém abre de dentro de um container.
COPY --chown=airflow:root analise/ /opt/cno/analise/

# O dashboard. Um diretório de 6 arquivos Python que lê o volume de dados pela
# mesma camada que o notebook — não há SQL aqui dentro.
COPY --chown=airflow:root app/ /opt/cno/app/

# Fumaça do dashboard, pelo mesmo motivo da anterior: `import streamlit` num venv
# onde o extra não foi instalado é um erro que só apareceria quando alguém
# abrisse o navegador.
RUN /opt/cno/.venv/bin/python -c "import sys; sys.path.insert(0, '/opt/cno'); import streamlit, altair; from analise import dados, estilo, malha; print('dashboard responde no ambiente da imagem')"

# O caminho do executável é o contrato entre a DAG e o pipeline. Fica no
# ENV da imagem para valer também em `docker run` direto, sem compose.
# O PATH de propósito NÃO recebe /opt/cno/.venv/bin: isso trocaria o `python`
# visto pelo Airflow pelo do venv do pipeline, que não tem Airflow dentro.
ENV CNO_BIN=/opt/cno/.venv/bin/cno \
    CNO_DATA_DIR=/opt/cno/data \
    CNO_REFERENCIAS_DIR=/opt/cno/analise
