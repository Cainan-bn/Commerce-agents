## Objetivo
Domínio puro (stdlib), persistência PostgreSQL (SQLAlchemy 2 async + Alembic), repositórios que implementam os ports da aplicação e carga idempotente do seed.

## Task Cards cobertos
- Líder: contrato do domínio (`docs/architecture/domain-model.md`) e ports de escrita (`OrderRepository.find/save`, `CustomerRepository`, `ReturnRequestRepository`, `ConversationRepository`)
- TASK-03-01 / 03-02 testes red do domínio (OPS, Hypothesis) e entidades/regras (CORE): máquina de estados do pedido, elegibilidade de devolução, frete grátis, cancelamento
- TASK-03-03 / 03-03b / 03-03c modelos, migrations 0001/0002 (checks, busca sem acento) e repositórios (CORE); `save` preserva o frete
- TASK-03-04 testes de integração com testcontainers pgvector/pg16 (OPS)
- TASK-03-05 `make seed-db` idempotente (OPS)

## ADRs criados
Nenhum (decisões cobertas pelos ADRs 0002 e 0005).

## Como verificar
```bash
make lint && make test
uv run pytest tests/integration -q      # exige Docker ativo
make up && make seed-db && make seed-db # contagens idênticas nas duas rodadas
```

## Métricas
- 252 testes (38 de integração), cobertura 98% (domínio e repositories.py a 100%); mypy --strict e 4 contratos import-linter verdes.
- Carga do seed: customers 200, products 300, variants 1770, orders 1000, items 1300, return_requests 80; idêntica na 2ª rodada.

## Defeitos achados na revisão do Líder
1. `delivered_at` sobrescrito ao negar devolução (corrigido no domínio).
2. `save` apagava carrier/cep/method de pedidos existentes via `merge` (corrigido, 03-03c; teste de regressão).

## Riscos / pendências
- `save` sem lock otimista: concorrência é last-write-wins (revisitar na Fase 07).
- `websearch_to_tsquery` usa AND e a cor não está em `search_vector`: "tênis preto" retorna vazio (tratar na Fase 05).
- `scripts/load_seed.py` fora do escopo do mypy; `return_request.status` do seed não tem coluna e é ignorado.
- Agentes CORE e OPS migraram para Claude (Sonnet e Haiku) por limite do plano no opencode.
