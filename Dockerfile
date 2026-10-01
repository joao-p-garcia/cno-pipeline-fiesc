# syntax=docker/dockerfile:1

ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:${AIRFLOW_VERSION}

USER root
RUN install -d -o airflow -g root -m 775 /opt/cno /opt/cno/data
USER airflow

RUN python -m venv /opt/cno/.venv \
    && /opt/cno/.venv/bin/pip install --no-cache-dir --upgrade pip

COPY --chown=airflow:root pyproject.toml /opt/cno/pacote/pyproject.toml
COPY --chown=airflow:root src /opt/cno/pacote/src
RUN /opt/cno/.venv/bin/pip install --no-cache-dir "/opt/cno/pacote[dashboard]"

RUN /opt/cno/.venv/bin/python -c "from cno_pipeline.curate.geocodificacao import decodificar; lat, lon = decodificar('584FPC38+X8'); assert -27.4 < lat < -27.2 and -50.7 < lon < -50.5, (lat, lon); print('geocodificação responde no ambiente da imagem')"

COPY --chown=airflow:root dags/ /opt/airflow/dags/

COPY --chown=airflow:root analise/ /opt/cno/analise/

COPY --chown=airflow:root app/ /opt/cno/app/

RUN /opt/cno/.venv/bin/python -c "import sys; sys.path.insert(0, '/opt/cno'); import streamlit, altair; from analise import dados, estilo, malha; print('dashboard responde no ambiente da imagem')"

ENV CNO_BIN=/opt/cno/.venv/bin/cno \
    CNO_DATA_DIR=/opt/cno/data \
    CNO_REFERENCIAS_DIR=/opt/cno/analise
