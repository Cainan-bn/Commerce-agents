# Backlog

Épicos → Task Cards. Cards da Fase 01 estão completos. Os das demais fases trazem agente, dependência e objetivo; o card completo (contexto, contratos fixos, critérios, commits) é emitido pelo LÍDER no início de cada fase, depois do merge da anterior, para refletir o que foi aprendido.

Regras: TDD por par (OPS escreve o teste em red, CORE implementa); escalonar ao LÍDER após 2 tentativas falhas; uma fase só começa após o merge da anterior.

## Épicos

| Épico | Fases | Responsáveis |
|---|---|---|
| E0 Planejamento e contratos | 00 | LÍDER |
| E1 Ambiente e CI | 01 | OPS |
| E2 Dados e loja mock | 02 | CORE, OPS |
| E3 Domínio e persistência | 03 | OPS, CORE |
| E4 Ferramentas MCP | 04 | LÍDER, OPS, CORE |
| E5 RAG de políticas | 05 | OPS, CORE |
| E6 Orquestração de agentes | 06 | LÍDER, OPS, CORE |
| E7 Canais e handoff | 07 | OPS, CORE |
| E8 Avaliação | 08 | OPS, CORE, LÍDER |
| E9 Resiliência, observabilidade, carga | 09 | OPS, CORE, LÍDER |
| E10 Deploy e release | 10 | OPS, LÍDER |

## Fase 01 — `fase/01-setup-ambiente`

### TASK-01-01: Criar bootstrap WSL2, Makefile e pré-commit
- **Agente:** OPS
- **Branch:** fase/01-setup-ambiente
- **Depende de:** nenhuma
- **Contexto (ler apenas):** `README.md`; seção 5 do prompt-mestre (colada pelo LÍDER no card); `.gitattributes`
- **Objetivo:** Entregar `scripts/bootstrap_wsl2.sh` idempotente, `Makefile` com os alvos mínimos, `.editorconfig` e `.pre-commit-config.yaml`.
- **Contratos fixos:** alvos `doctor setup up down seed migrate lint test test-e2e eval load run`; scripts `.sh` em LF e `chmod +x`; o script nunca sobrescreve `.env`.
- **Critérios de aceite:** `shellcheck scripts/*.sh` limpo; `bash scripts/bootstrap_wsl2.sh` roda 2× sem erro e sem mudanças na 2ª; aborta com mensagem clara fora do WSL2 e sob `/mnt/`; `make doctor` lista toolchain, docker, gh e portas.
- **Fora do escopo:** instalar Docker; lógica de domínio.
- **Commits esperados:** `chore(infra): script de bootstrap WSL2` → `chore(infra): Makefile com alvos mínimos` → `chore(infra): editorconfig e pre-commit`
- **Entrega:** DONE-REPORT

### TASK-01-02: Configurar projeto Python, lint, tipos, testes e import-linter
- **Agente:** OPS
- **Branch:** fase/01-setup-ambiente
- **Depende de:** TASK-01-01
- **Contexto (ler apenas):** `docs/architecture/quality-targets.md`; `docs/adr/0002-*.md`; `src/commerce_agents/` (estrutura)
- **Objetivo:** Criar `pyproject.toml` (uv, Python 3.12) com ruff, `mypy --strict`, pytest (`pytest-asyncio`, `pytest-cov`, `hypothesis`) e contratos `layers` e `forbidden` do import-linter.
- **Contratos fixos:** pacote `commerce_agents` em `src/`; cobertura com branch; metas de `quality-targets.md`.
- **Critérios de aceite:** `make lint` e `make test` verdes sobre o código de contratos já existente e uma suíte mínima; um import proibido de teste (`domain` → `infrastructure`) quebra o import-linter.
- **Fora do escopo:** alterar código de produção além de configuração.
- **Commits esperados:** `chore: pyproject com uv e ferramentas` → `chore(lint): contratos do import-linter` → `test: suíte mínima de fumaça`
- **Entrega:** DONE-REPORT

### TASK-01-03: Criar docker-compose da stack local
- **Agente:** OPS
- **Branch:** fase/01-setup-ambiente
- **Depende de:** TASK-01-01
- **Contexto (ler apenas):** `docs/architecture/c4-container.md`; `docs/adr/0005-*.md`, `0006-*.md`
- **Objetivo:** `docker-compose.yml` com healthchecks para postgres 16 + pgvector, redis, redpanda, otel-collector, jaeger e langfuse; `.env.example` sem segredos.
- **Contratos fixos:** nomes de serviço `postgres redis redpanda otel-collector jaeger langfuse`.
- **Critérios de aceite:** `make up` leva todos a `healthy`; `make down` limpa; `detect-secrets scan` sem achados.
- **Fora do escopo:** compose de produção (Fase 10).
- **Commits esperados:** `chore(infra): docker-compose da stack local` → `chore(infra): env.example`
- **Entrega:** DONE-REPORT

### TASK-01-04: Criar CI no GitHub Actions
- **Agente:** OPS
- **Branch:** fase/01-setup-ambiente
- **Depende de:** TASK-01-02, TASK-01-03
- **Contexto (ler apenas):** `Makefile`; `pyproject.toml`
- **Objetivo:** Workflow lint → testes unitários → testes de integração (testcontainers) → build da imagem, com cache do uv.
- **Contratos fixos:** o CI chama apenas alvos do Makefile.
- **Critérios de aceite:** CI verde em PR; falha se o lint falhar.
- **Fora do escopo:** gate de eval (Fase 08); push para GHCR (Fase 10).
- **Commits esperados:** `ci: workflow de lint e testes` → `ci: build da imagem`
- **Entrega:** DONE-REPORT

## Fase 02 — `fase/02-dados-e-seed`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-02-01 | CORE | 01 | Gerador determinístico (seed fixa): ~300 SKUs, ~1.000 pedidos, ~200 clientes fictícios em `data/generators/` |
| TASK-02-02 | CORE | 01 | Corpus de políticas em Markdown com casos de borda |
| TASK-02-03 | CORE | 02-01, 02-02 | Golden set ≥ 60 cenários YAML, incluindo injection e ambiguidade; reservar holdout |
| TASK-02-04 | OPS | 02-01 | `mock_store/` FastAPI com latência e falhas injetáveis; testes de contrato |
| TASK-02-05 | OPS | 02-04 | `make seed` idempotente |

## Fase 03 — `fase/03-dominio-e-persistencia`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-03-01 | OPS | 02 | Testes do domínio (inclui Hypothesis: transições de `OrderStatus`, prazo de troca) |
| TASK-03-02 | CORE | 03-01 | Entidades, VOs e regras puras em `domain/` |
| TASK-03-03 | CORE | 03-02 | Modelos SQLAlchemy 2 async, migrations Alembic derivadas dos dados da Fase 02, repositórios |
| TASK-03-04 | OPS | 03-03 | Testes de integração dos repositórios com testcontainers |

## Fase 04 — `fase/04-ferramentas-mcp`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-04-01 | LÍDER | 03 | Schemas das ferramentas: input/output, erros tipados, `irreversible` |
| TASK-04-02 | OPS | 04-01 | Testes de contrato contra o mock_store, com timeout e 5xx |
| TASK-04-03 | CORE | 04-02 | Servidores MCP `orders`, `catalog`, `shipping`, `returns` |
| TASK-04-04 | CORE | 04-01 | `ConfirmIrreversibleAction` com token de uso único e expiração (testes red de OPS antes) |

## Fase 05 — `fase/05-rag-politicas`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-05-01 | OPS | 04 | Testes: chunking determinístico, idempotência de ingestão, recall@k |
| TASK-05-02 | CORE | 05-01 | Ingestão, índices `tsvector` (portuguese) e `pgvector` (HNSW) |
| TASK-05-03 | CORE | 05-02 | Busca híbrida com RRF, reranker atrás de feature flag, citações |
| TASK-05-04 | LÍDER | 05-03 | ADR complementar se o reranker entrar no caminho padrão |

## Fase 06 — `fase/06-orquestrador-agentes`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-06-01 | LÍDER | 05 | Desenho do grafo, allowlists, pontos de interrupção |
| TASK-06-02 | OPS | 06-01 | Testes do grafo com LLM fake roteirizado |
| TASK-06-03 | CORE | 06-02 | Supervisor + 4 especialistas, checkpointer PostgreSQL, memória do cliente |
| TASK-06-04 | CORE | 06-02 | `IntentRouter` baseline com saída estruturada |
| TASK-06-05 | CORE | 06-03 | Defesa contra prompt injection (ADR 0010) |
| TASK-06-06 | LÍDER | 06-03..05 | Revisão de determinismo das decisões críticas |

## Fase 07 — `fase/07-canais-e-handoff`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-07-01 | OPS | 06 | Testes: normalização, deduplicação, ordem, outbox |
| TASK-07-02 | CORE | 07-01 | Webhooks → Redpanda → consumidor → `HandleInboundMessage`; outbox |
| TASK-07-03 | CORE | 07-01 | `RequestHandoff` com resumo e push WebSocket |
| TASK-07-04 | OPS | 07-03 | Painel mínimo de handoff e testes de componentes |

## Fase 08 — `fase/08-evals-e-ajuste-de-prompts`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-08-01 | OPS | 07 | Harness com simulador de cliente e coleta de traces |
| TASK-08-02 | OPS | 08-01 | Métricas determinísticas |
| TASK-08-03 | CORE | 08-01 | LLM-as-judge com rubrica e calibração em ~30 conversas rotuladas |
| TASK-08-04 | OPS | 08-02, 08-03 | Commit `eval: baseline v1` com relatório |
| TASK-08-05 | CORE | 08-04 | Ajustes de prompt, um commit por hipótese |
| TASK-08-06 | OPS | 08-05 | `eval: resultado após ajuste` (antes × depois) |
| TASK-08-07 | OPS | 08-06 | `make eval` como gate de CI |
| TASK-08-08 | LÍDER | 08-06 | Revisão anti-overfitting com holdout |

## Fase 09 — `fase/09-resiliencia-observabilidade-carga`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-09-01 | OPS | 08 | Testes de caos (mock_store e provider de LLM) |
| TASK-09-02 | CORE | 09-01 | Circuit breaker, retry, fallback, orçamento de tokens, cache semântico |
| TASK-09-03 | CORE | 08 | OpenTelemetry (spans por nó e ferramenta) e Langfuse |
| TASK-09-04 | OPS | 09-03 | Dashboards como código |
| TASK-09-05 | OPS | 09-02, 09-03 | Scripts k6 e relatório em `load/reports/` |
| TASK-09-06 | LÍDER | 09-05 | ADR de resultados e gargalos |

## Fase 10 — `fase/10-deploy-e-release`

| Card | Agente | Depende de | Objetivo |
|---|---|---|---|
| TASK-10-01 | OPS | 09 | Dockerfiles multi-stage, GHCR, Trivy |
| TASK-10-02 | OPS | 10-01 | `docker-compose.prod.yml`, migrations como job |
| TASK-10-03 | OPS | 10-02 | Workflow de deploy com smoke test |
| TASK-10-04 | LÍDER | 10-03 | README final como case de portfólio |
| TASK-10-05 | LÍDER | 10-04 | Revisão final, tag `v1.0.0`, GitHub Release |
