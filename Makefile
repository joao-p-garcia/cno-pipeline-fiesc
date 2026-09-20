.DEFAULT_GOAL := help

# Configuração local opcional, não versionada. Serve para apontar CNO_DATA_DIR
# para fora do repositório — útil quando o código está numa pasta montada
# (/mnt/c no WSL) e os dados devem ficar num disco nativo, bem mais rápido.
# Veja .env.exemplo.
-include .env
export

VENV := .venv
PIP := $(VENV)/bin/pip
CNO := $(VENV)/bin/cno

# Os testes da DAG precisam do Airflow, que vive no seu próprio venv.
# Sobrescrevível para o CI e o container apontarem o deles.
AIRFLOW_VENV ?= $(HOME)/.venvs/airflow

.PHONY: help setup info extract extract-force transform validate curate pipeline \
        test test-dag lint fmt clean clean-data dashboard notebook \
        build up down down-tudo logs ps dag-run docker-pipeline

# O -h é necessário porque o `-include .env` acrescenta um segundo arquivo ao
# MAKEFILE_LIST, e sem ele o grep prefixaria cada linha com o nome do arquivo.
help:  ## Lista os alvos disponíveis
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

$(VENV):
	python3 -m venv $(VENV)

# Sentinela: o pip só roda de novo quando o pyproject.toml muda. Sem isto, todo
# alvo pagaria um `pip install` — caro quando o repositório está montado em
# /mnt/c, onde operações com muitos arquivos pequenos são lentas.
STAMP := $(VENV)/.instalado

$(STAMP): pyproject.toml | $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -e ".[dev]" --quiet
	@touch $(STAMP)
	@echo "dependências instaladas"

setup: $(STAMP)  ## Cria o venv e instala o projeto em modo editável

info: setup  ## Compara a fonte com o estado local, sem baixar nada
	$(CNO) info

extract: setup  ## Baixa e materializa a camada raw (pula se já estiver atualizado)
	$(CNO) extract

extract-force: setup  ## Rebaixa mesmo que o snapshot local esteja atualizado
	$(CNO) extract --force

transform: setup  ## Trata a camada raw e materializa parquet em staging
	$(CNO) transform

validate: setup  ## Valida a camada tratada e reconcilia com os totais oficiais
	$(CNO) validate

curate: setup  ## Modela a camada curada e os marts que a análise consome
	$(CNO) curate

pipeline: extract transform validate curate  ## Roda o pipeline inteiro, na ordem

# -- análise -------------------------------------------------------------
# O dashboard e o notebook leem a camada curada; não a produzem. Rode
# `make pipeline` antes, ou deixe a DAG rodar.

ANALISE := $(VENV)/.analise

# Sentinela própria: os extras da análise são pesados (Streamlit, JupyterLab) e
# quem só quer rodar o pipeline não deve pagar por eles no `make test`.
$(ANALISE): pyproject.toml | $(VENV)
	$(PIP) install -e ".[dashboard,notebook]" --quiet
	@touch $(ANALISE)

dashboard: $(ANALISE)  ## Sobe o dashboard narrativo em http://localhost:8501
	$(VENV)/bin/streamlit run app/dashboard.py

notebook: $(ANALISE)  ## Reexecuta o notebook de exploração, gravando as saídas
	$(VENV)/bin/jupyter execute --inplace analise/exploracao.ipynb

test: setup  ## Roda a suíte de testes (offline)
	$(VENV)/bin/pytest

test-dag:  ## Roda os testes da DAG (exige o venv do Airflow)
	@test -x "$(AIRFLOW_VENV)/bin/pytest" \
		|| { echo "venv do Airflow não encontrado em $(AIRFLOW_VENV)"; \
		     echo "defina AIRFLOW_VENV=<caminho> — veja o README"; exit 1; }
	AIRFLOW_HOME=$(HOME)/airflow AIRFLOW__CORE__LOAD_EXAMPLES=False \
		$(AIRFLOW_VENV)/bin/pytest tests/test_dag.py

lint: setup  ## Verifica estilo e erros estáticos
	$(VENV)/bin/ruff check src tests dags analise app
	$(VENV)/bin/ruff format --check src tests dags analise app

fmt: setup  ## Formata o código
	$(VENV)/bin/ruff format src tests dags analise app
	$(VENV)/bin/ruff check --fix src tests dags analise app

clean:  ## Remove artefatos de build e cache
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

clean-data:  ## Apaga a camada de dados (ela é reproduzível com 'make extract')
	rm -rf data/raw data/staging data/curated

# -- container ------------------------------------------------------------
# A stack de entrega. Desenvolvimento continua rodando direto no host, com os
# alvos acima; estes existem para quem clona o repositório e quer ver tudo de
# pé sem instalar Airflow, Postgres nem Python na mão.

COMPOSE := docker compose

build:  ## Constrói a imagem (Airflow + pipeline em venv próprio)
	$(COMPOSE) build

up:  ## Sobe a stack completa em container e deixa a UI do Airflow no ar
	$(COMPOSE) up -d --build
	@echo
	@echo "Airflow   em http://localhost:$(or $(AIRFLOW_PORTA),8080)  (usuário airflow / senha airflow)"
	@echo "Dashboard em http://localhost:$(or $(DASHBOARD_PORTA),8501)"
	@echo "A DAG cno_pipeline sobe despausada e ja comeca a rodar: primeira"
	@echo "execucao baixa ~315 MB da Receita e leva ~2min. Acompanhe com 'make logs'."
	@echo "Para disparar outra: 'make dag-run'."

down:  ## Derruba os containers, preservando os dados já materializados
	$(COMPOSE) down

down-tudo:  ## Derruba e apaga também os volumes (dados, logs e banco do Airflow)
	$(COMPOSE) down --volumes

logs:  ## Acompanha os logs da stack
	$(COMPOSE) logs -f

ps:  ## Mostra o estado dos serviços
	$(COMPOSE) ps

dag-run:  ## Dispara uma execução da DAG no Airflow em container
	$(COMPOSE) exec airflow-scheduler airflow dags trigger cno_pipeline

# Roda as três etapas em containers efêmeros, sem orquestrador nenhum. Escreve
# no mesmo volume que a DAG usa, então serve tanto de demonstração rápida
# quanto de pré-aquecimento antes de subir o Airflow.
docker-pipeline:  ## Roda o pipeline inteiro em container, sem Airflow
	$(COMPOSE) run --rm cno extract
	$(COMPOSE) run --rm cno transform
	$(COMPOSE) run --rm cno validate
	$(COMPOSE) run --rm cno curate
