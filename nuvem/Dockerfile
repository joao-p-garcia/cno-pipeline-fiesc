# syntax=docker/dockerfile:1

# A imagem da nuvem, que é a da raiz sem o Airflow. Aqui quem orquestra é o
# Container Apps Job, então a base do Airflow custaria ~700 MB e um resolvedor
# rígido por nada. Uma imagem serve os dois papéis, job e dashboard, e quem
# decide qual é o `command` de cada recurso no Terraform.
FROM python:3.12-slim

# azcopy é o que fala com o lake. Binário único, em vez dos ~500 MB do Azure CLI.
ARG AZCOPY_URL=https://aka.ms/downloadazcopy-v10-linux
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    curl -sSL "$AZCOPY_URL" -o /tmp/azcopy.tar.gz; \
    tar -xzf /tmp/azcopy.tar.gz -C /tmp; \
    install -m 0755 /tmp/azcopy_linux_amd64_*/azcopy /usr/local/bin/azcopy; \
    rm -rf /tmp/azcopy*; \
    apt-get purge -y curl; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

# Usuário não-root, porque o job baixa e descompacta 315 MB de fonte pública.
RUN useradd --create-home --uid 10001 cno \
    && install -d -o cno -g cno /opt/cno /opt/cno/data

USER cno
WORKDIR /opt/cno

RUN python -m venv /opt/cno/.venv \
    && /opt/cno/.venv/bin/pip install --no-cache-dir --upgrade pip

# Instalado de verdade e não editável, porque a imagem é artefato de entrega. O
# extra `dashboard` entra porque a mesma imagem serve os dois papéis.
COPY --chown=cno:cno pyproject.toml /opt/cno/pacote/pyproject.toml
COPY --chown=cno:cno src /opt/cno/pacote/src
RUN /opt/cno/.venv/bin/pip install --no-cache-dir "/opt/cno/pacote[dashboard]"

# Testes de fumaça em tempo de build, como na imagem da raiz. Dependência
# declarada só implicitamente passa aqui e quebra no primeiro venv limpo.
RUN /opt/cno/.venv/bin/python -c "from cno_pipeline.curate.geocodificacao import decodificar; lat, lon = decodificar('584FPC38+X8'); assert -27.4 < lat < -27.2 and -50.7 < lon < -50.5, (lat, lon); print('geocodificacao responde')"

COPY --chown=cno:cno analise/ /opt/cno/analise/
COPY --chown=cno:cno app/ /opt/cno/app/

RUN /opt/cno/.venv/bin/python -c "import sys; sys.path.insert(0, '/opt/cno'); import streamlit, altair; from analise import dados, estilo, malha; print('dashboard responde')"

# O .gitattributes mantém o LF, mas o bit de execução não sobrevive a um
# checkout no Windows.
COPY --chown=cno:cno nuvem/entrypoint-job.sh nuvem/entrypoint-dashboard.sh /opt/cno/nuvem/
RUN chmod +x /opt/cno/nuvem/entrypoint-job.sh /opt/cno/nuvem/entrypoint-dashboard.sh

ENV CNO_BIN=/opt/cno/.venv/bin/cno \
    CNO_DATA_DIR=/opt/cno/data \
    CNO_REFERENCIAS_DIR=/opt/cno/analise \
    PATH=/opt/cno/.venv/bin:$PATH

# Sem CMD, cada recurso do Terraform declara o seu `command`.
