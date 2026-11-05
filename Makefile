SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

.DEFAULT_GOAL := help
.PHONY: help doctor setup up down seed migrate lint test test-e2e eval load run

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

seed: ## Popula dados mock
	@echo "[seed] nao implementado nesta fase"

migrate: ## Aplica migracoes
	@echo "[migrate] nao implementado nesta fase"

lint: ## Roda ruff, format check, mypy --strict e import-linter
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict src
	uv run lint-imports

test: ## Roda a suite de testes
	uv run pytest

test-e2e: ## Roda testes end-to-end
	@echo "[test-e2e] nao implementado nesta fase"

eval: ## Roda a suite de avaliacao
	@echo "[eval] nao implementado nesta fase"

load: ## Roda teste de carga k6
	@echo "[load] nao implementado nesta fase"

run: ## Sobe a aplicacao localmente
	@echo "[run] nao implementado nesta fase"
