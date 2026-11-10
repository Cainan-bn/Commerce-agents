SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

.DEFAULT_GOAL := help
.PHONY: help doctor setup up up-langfuse down seed migrate lint build test test-unit test-integration test-e2e eval eval-quick eval-holdout eval-record eval-ci load load-caos-fallback demo-record demo-verify run mock seed-db ingest-policies eval-rag test-panel run-api run-worker

SEED_OUT ?= data/seed
DEMO_CASSETTE ?= data/demo/cassette.jsonl
DEMO_API_URL ?= http://localhost:8000
PROD_COMPOSE ?= docker compose -f docker-compose.prod.yml

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

up-langfuse: ## Sobe a stack local com o exporter do Langfuse no collector (exige LANGFUSE_OTLP_AUTH)
	docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d

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

seed-db: migrate ## Carga idempotente de data/seed no Postgres (roda 2x sem duplicar)
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	uv run python scripts/load_seed.py --data-dir "$(SEED_OUT)"

migrate: ## Aplica as migracoes do Alembic (DATABASE_URL ou POSTGRES_* do .env)
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	uv run python -c "from commerce_agents.infrastructure.persistence.migrate import upgrade_to_head, sync_url_from_env; upgrade_to_head(sync_url_from_env())"

ingest-policies: ## Indexa data/policies no Postgres (idempotente; modelo de embeddings do .env)
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	uv run python -m commerce_agents.infrastructure.rag

eval-rag: ## Mede recall@4 e MRR do RAG com o modelo real (marcador embeddings; fora do make test)
	uv run pytest tests/quality -m embeddings --no-cov -s

test-panel: ## Roda os testes de componentes do painel (node --test + jsdom)
	cd panel && npm ci && node --test test/

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

eval: ## Roda a suite de avaliacao dev completa (LABEL=nome; grava reports/eval)
	uv run python -m evals run --label "$(or $(LABEL),local)" --subset all --split dev --retry-infra 2

eval-quick: ## Roda o subset rapido de 12 cenarios para PR (LABEL=nome)
	uv run python -m evals run --label "$(or $(LABEL),quick)" --subset quick --split dev --retry-infra 2

EVAL_CASSETTE_QUICK := evals/cassettes/quick.jsonl

eval-record: ## Grava o cassete de replay do subset quick com o LLM real (opencode; ADR 0016)
	uv run python -m evals run --label record --subset quick --split dev --retry-infra 3 --record $(EVAL_CASSETTE_QUICK)

eval-ci: ## Gate de CI: replay do cassete do subset quick, sem LLM nem Postgres (ADR 0016)
	LLM_PROVIDER=replay EVAL_CASSETTE=$(EVAL_CASSETTE_QUICK) \
		uv run python -m evals run --label ci --subset quick --split dev --retry-infra 0
	uv run python -m evals gate --cassette $(EVAL_CASSETTE_QUICK) \
		--report "$$(ls -t reports/eval/*-ci.json | head -n 1)"

eval-holdout: ## Roda o holdout (so o Lider; exige EVAL_HOLDOUT_DIR fora do repositorio)
	uv run python -m evals run --label "$(or $(LABEL),holdout)" --subset all --split holdout

load: ## Carga k6 (SCENARIO=webhook|conversa|caos|trace|all; APP_DIR=worktree; ver load/README.md)
	@for scenario in $(if $(filter all,$(or $(SCENARIO),all)),webhook conversa caos trace,$(SCENARIO)); do \
		echo "[load] cenario $$scenario"; \
		load/run.sh $$scenario || exit $$?; \
	done

load-caos-fallback: ## Caos com LLM_FALLBACK_* = 2o stub (remedicao do ADR 0019; mesmas variaveis de make load)
	FALLBACK=1 load/run.sh caos

demo-record: ## Grava o cassete da demo pelo caminho real (opencode no host; so o autor; ADR 0020)
	docker compose up -d postgres redpanda otel-collector jaeger
	$(MAKE) --no-print-directory seed-db ingest-policies
	@set -a; if [ -f .env ]; then . ./.env; fi; set +a; \
	: "$${LLM_MODEL:?defina LLM_MODEL (modelo do opencode, provedor/modelo)}"; \
	rm -f $(DEMO_CASSETTE); \
	export DEMO_MODE=true LLM_PROVIDER=opencode-cli LLM_RECORD_TO=$(DEMO_CASSETTE) \
		WEB_SESSION_SECRET=$${WEB_SESSION_SECRET:-demo-record-local}; \
	uv run uvicorn commerce_agents.interfaces.main:app --port 8000 & api=$$!; \
	uv run python -m commerce_agents.interfaces.worker all & worker=$$!; \
	trap 'kill $$api $$worker 2> /dev/null || true' EXIT; \
	for i in $$(seq 1 60); do curl -sf $(DEMO_API_URL)/health > /dev/null && break; sleep 1; done; \
	uv run python scripts/demo_drive.py --api-url $(DEMO_API_URL) --timeout 300

demo-verify: ## Reproduz o cassete da demo na stack de producao e falha fora do roteiro (DEMO_KEEP=1 mantem no ar)
	@test -f $(DEMO_CASSETTE) || { echo "[demo-verify] $(DEMO_CASSETTE) ausente: rode make demo-record"; exit 1; }
	@export DEMO_MODE=true LLM_PROVIDER=recorded LLM_CASSETTE=/app/data/demo/cassette.jsonl \
		APP_IMAGE=$${APP_IMAGE:-commerce-agents:local} \
		POSTGRES_PASSWORD=$${POSTGRES_PASSWORD:-demo-local} WEB_SESSION_SECRET=$${WEB_SESSION_SECRET:-demo-local} \
		PANEL_TOKEN=$${PANEL_TOKEN:-demo-local} GRAFANA_ADMIN_PASSWORD=$${GRAFANA_ADMIN_PASSWORD:-demo-local}; \
	$(PROD_COMPOSE) up -d --build; \
	trap '[ "$${DEMO_KEEP:-0}" = 1 ] || $(PROD_COMPOSE) down' EXIT; \
	for i in $$(seq 1 120); do curl -sf $(DEMO_API_URL)/health > /dev/null && break; sleep 2; done; \
	uv run python scripts/demo_drive.py --api-url $(DEMO_API_URL) --timeout 120 --expect-no-miss

run-api: ## Sobe a API de canais e o painel (porta 8000; requer Postgres e Redpanda do compose)
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	uv run uvicorn commerce_agents.interfaces.main:app --port 8000

run-worker: ## Sobe os workers (inbound, relay e sender) do pipeline de mensagens
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	uv run python -m commerce_agents.interfaces.worker all

run: ## Sobe a aplicacao localmente
	@echo "[run] nao implementado nesta fase"

mock: ## Sobe a API fake da loja (mock_store) na porta 8001
	uv run uvicorn mock_store.main:app --port 8001
