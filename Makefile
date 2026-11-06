SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

.DEFAULT_GOAL := help
.PHONY: help doctor setup up down seed migrate lint build test test-unit test-integration test-e2e eval load run mock

SEED_OUT ?= data/seed

help: ## Lista os alvos disponiveis
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

doctor: ## Verifica toolchain, docker, gh e portas (nao falha por ferramenta ausente)
	@bash scripts/doctor.sh

setup: ## Instala dependencias do projeto e hooks de pre-commit
	@if [ -f pyproject.toml ]; then \
		echo "[setup] uv sync"; \
		uv sync; \
	else \
		echo "[setup] pyproject.toml ausente; nada a sincronizar (TASK-01-02)"; \
	fi
	@if [ -f .pre-commit-config.yaml ] && command -v pre-commit >/dev/null 2>&1; then \
		echo "[setup] pre-commit install"; \
		pre-commit install; \
		pre-commit install --hook-type commit-msg; \
	else \
		echo "[setup] pre-commit indisponivel; rode scripts/bootstrap_wsl2.sh"; \
	fi
	@if [ -f package-lock.json ]; then \
		echo "[setup] npm ci"; \
		npm ci; \
	else \
		echo "[setup] package-lock.json ausente; pulando npm ci"; \
	fi
	@if [ ! -f .env ] && [ -f .env.example ]; then \
		echo "[setup] criando .env a partir de .env.example"; \
		cp .env.example .env; \
	fi

up: ## Sobe a stack local com docker compose
	@if [ -f docker-compose.yml ] || [ -f compose.yaml ] || [ -f compose.yml ]; then \
		docker compose up -d; \
	else \
		echo "[up] docker-compose.yml ausente (TASK-01-03); nada a subir"; \
	fi

down: ## Derruba a stack local
	@if [ -f docker-compose.yml ] || [ -f compose.yaml ] || [ -f compose.yml ]; then \
		docker compose down; \
	else \
		echo "[down] docker-compose.yml ausente (TASK-01-03); nada a derrubar"; \
	fi

# A carga em PostgreSQL nao faz parte desta fase: as migrations da Fase 03
# serao derivadas destes dados de seed.
seed: ## Regenera data/seed e valida a carga pelo mock_store
	uv run python -m data.generators --seed 42 --out "$(SEED_OUT)"
	uv run python scripts/validate_seed.py "$(SEED_OUT)"

migrate: ## Aplica migracoes
	@echo "[migrate] nao implementado nesta fase"

lint: ## Roda ruff, format check, mypy --strict e import-linter
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict src mock_store data
	uv run lint-imports

build: ## Constroi a imagem Docker da aplicacao
	docker build -t commerce-agents:local .

test: ## Roda a suite de testes
	uv run pytest

test-unit: ## Roda apenas os testes unitarios (gera coverage.xml)
	uv run pytest tests/unit -m unit --cov-report=xml:coverage.xml --cov-report=term-missing

test-integration: ## Roda testes de integracao (aceita suite vazia)
	@status=0; \
	uv run pytest tests/integration -m integration --no-cov || status=$$?; \
	if [ $$status -eq 5 ]; then \
		echo "[test-integration] nenhum teste de integracao nesta fase"; \
		exit 0; \
	fi; \
	exit $$status

test-e2e: ## Roda testes end-to-end
	@echo "[test-e2e] nao implementado nesta fase"

eval: ## Roda a suite de avaliacao
	@echo "[eval] nao implementado nesta fase"

load: ## Roda teste de carga k6
	@echo "[load] nao implementado nesta fase"

run: ## Sobe a aplicacao localmente
	@echo "[run] nao implementado nesta fase"

mock: ## Sobe a API fake da loja (mock_store) na porta 8001
	uv run uvicorn mock_store.main:app --port 8001
