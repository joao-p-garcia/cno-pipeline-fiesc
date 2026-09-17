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

.PHONY: help setup info extract extract-force transform validate pipeline \
        test test-dag lint fmt clean clean-data

# O -h é necessário porque o `-include .env` acrescenta um segundo arquivo ao
# MAKEFILE_LIST, e sem ele o grep prefixaria cada linha com o nome do arquivo.
help:  ## Lista os alvos disponíveis
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

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

pipeline: extract transform validate  ## Roda o pipeline inteiro, na ordem

test: setup  ## Roda a suíte de testes (offline)
	$(VENV)/bin/pytest

test-dag:  ## Roda os testes da DAG (exige o venv do Airflow)
	@test -x "$(AIRFLOW_VENV)/bin/pytest" \
		|| { echo "venv do Airflow não encontrado em $(AIRFLOW_VENV)"; \
		     echo "defina AIRFLOW_VENV=<caminho> — veja o README"; exit 1; }
	AIRFLOW_HOME=$(HOME)/airflow AIRFLOW__CORE__LOAD_EXAMPLES=False \
		$(AIRFLOW_VENV)/bin/pytest tests/test_dag.py

lint: setup  ## Verifica estilo e erros estáticos
	$(VENV)/bin/ruff check src tests dags
	$(VENV)/bin/ruff format --check src tests dags

fmt: setup  ## Formata o código
	$(VENV)/bin/ruff format src tests dags
	$(VENV)/bin/ruff check --fix src tests dags

clean:  ## Remove artefatos de build e cache
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

clean-data:  ## Apaga a camada de dados (ela é reproduzível com 'make extract')
	rm -rf data/raw data/staging data/curated
