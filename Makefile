.DEFAULT_GOAL := help
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help setup info extract extract-force test lint fmt clean clean-data

help:  ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV):
	python3 -m venv $(VENV)

setup: $(VENV)  ## Cria o venv e instala o projeto em modo editável
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -e ".[dev]" --quiet
	@echo "pronto: use 'make info' ou 'make extract'"

info: setup  ## Compara a fonte com o estado local, sem baixar nada
	$(VENV)/bin/cno info

extract: setup  ## Baixa e materializa a camada raw (pula se já estiver atualizado)
	$(VENV)/bin/cno extract

extract-force: setup  ## Rebaixa mesmo que o snapshot local esteja atualizado
	$(VENV)/bin/cno extract --force

test: setup  ## Roda a suíte de testes (offline)
	$(VENV)/bin/pytest

lint: setup  ## Verifica estilo e erros estáticos
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/ruff format --check src tests

fmt: setup  ## Formata o código
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests

clean:  ## Remove artefatos de build e cache
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

clean-data:  ## Apaga a camada de dados (ela é reproduzível com 'make extract')
	rm -rf data/raw data/staging data/curated
