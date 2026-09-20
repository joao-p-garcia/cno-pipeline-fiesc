# syntax=docker/dockerfile:1

# A imagem da nuvem. É a da raiz sem o Airflow.
#
# Lá a base é `apache/airflow` porque a entrega local empacota o orquestrador
# junto. Aqui quem orquestra é o Container Apps Job, então carregar o Airflow
# seria pagar ~700 MB e o resolvedor de dependências dele — que é rígido por
# necessidade — por nada. O venv do pipeline já era isolado em /opt/cno/.venv,
# o que torna a troca de base quase mecânica.
#
# Uma imagem, dois papéis: o job e o dashboard saem daqui, e quem decide qual é
# qual é o `command` de cada recurso no Terraform. É a mesma escolha que o
# compose faz com os serviços `cno` e `dashboard`.
FROM python:3.12-slim

# azcopy é o que fala com o lake. Binário único, sem SDK e sem o Azure CLI
# inteiro (que traria ~500 MB para fazer uma cópia de diretório).
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

# Usuário não-root. O job baixa 315 MB de uma fonte pública e os descompacta;
# não há razão para isso acontecer como root, e a extração já recusa membros de
# zip com caminho (zip-slip) por conta própria.
RUN useradd --create-home --uid 10001 cno \
    && install -d -o cno -g cno /opt/cno /opt/cno/data

USER cno
WORKDIR /opt/cno

RUN python -m venv /opt/cno/.venv \
    && /opt/cno/.venv/bin/pip install --no-cache-dir --upgrade pip

# Instalado de verdade, não editável: a imagem é artefato de entrega. O extra
# `dashboard` entra porque a mesma imagem serve os dois papéis; o extra
# `notebook` fica de fora, como na imagem da raiz.
COPY --chown=cno:cno pyproject.toml /opt/cno/pacote/pyproject.toml
COPY --chown=cno:cno src /opt/cno/pacote/src
RUN /opt/cno/.venv/bin/pip install --no-cache-dir "/opt/cno/pacote[dashboard]"

# Os mesmos dois testes de fumaça em tempo de build da imagem da raiz. Eles
# existem porque dependência declarada só implicitamente passa na máquina de
# quem desenvolve e quebra no primeiro venv limpo — já aconteceu neste projeto.
RUN /opt/cno/.venv/bin/python -c "from cno_pipeline.curate.geocodificacao import decodificar; lat, lon = decodificar('584FPC38+X8'); assert -27.4 < lat < -27.2 and -50.7 < lon < -50.5, (lat, lon); print('geocodificacao responde')"

COPY --chown=cno:cno analise/ /opt/cno/analise/
COPY --chown=cno:cno app/ /opt/cno/app/

RUN /opt/cno/.venv/bin/python -c "import sys; sys.path.insert(0, '/opt/cno'); import streamlit, altair; from analise import dados, estilo, malha; print('dashboard responde')"

# Os dois papéis. O chmod é cinto e suspensório: o .gitattributes já mantém
# estes arquivos em LF, mas o bit de execução não sobrevive a um checkout no
# Windows.
COPY --chown=cno:cno nuvem/entrypoint-job.sh nuvem/entrypoint-dashboard.sh /opt/cno/nuvem/
RUN chmod +x /opt/cno/nuvem/entrypoint-job.sh /opt/cno/nuvem/entrypoint-dashboard.sh

ENV CNO_BIN=/opt/cno/.venv/bin/cno \
    CNO_DATA_DIR=/opt/cno/data \
    CNO_REFERENCIAS_DIR=/opt/cno/analise \
    PATH=/opt/cno/.venv/bin:$PATH

# Sem CMD: cada recurso do Terraform declara o seu `command`, e um default aqui
# só serviria para mascarar um esquecimento lá.
