## Objetivo
Ferramentas dos agentes atrás de um contrato único: schemas estritos, erros tipados, allowlist por agente e ações irreversíveis protegidas por token de uso único e idempotência, aplicadas no servidor da ferramenta (independente do LLM).

## Task Cards cobertos
- TASK-04-01 (Líder): `application/dto/tools.py` (10 ferramentas, `TOOL_SPECS`, `AGENT_ALLOWLIST`, `action_digest`), ports `ToolInvoker` e `IdempotencyRegistry`, DTOs de confirmação, `docs/architecture/tools.md`
- TASK-04-02 / 04-02b testes de contrato do executor contra o mock_store (OPS); defeitos dos testes red corrigidos
- TASK-04-03 `ToolExecutor` e servidores MCP orders/catalog/shipping/returns (CORE)
- TASK-04-04r / 04-04g casos de uso de confirmação e adaptadores Postgres de token e idempotência (OPS red, CORE green)

## ADRs criados
- 0011 Consumo do token de confirmação no servidor da ferramenta (refina o 0008), com marcador PENDENTE para retomada após erro transitório.

## Como verificar
```bash
make lint && make test
make up && make migrate && make seed-db && make mock   # em outro terminal
python -m commerce_agents.infrastructure.mcp orders --agent Pedidos   # exige DATABASE_URL/POSTGRES_*
```

## Métricas
- 496 testes, cobertura 99% (infrastructure/mcp, casos de uso e adaptadores a 100%); mypy --strict e 4 contratos import-linter verdes.
- Verificação do Líder de ponta a ponta (MCP via stdio, Postgres, mock_store): token emitido por um processo e consumido por outro; token forjado recusado; cancelamento executado uma vez; replay com a mesma chave devolve o mesmo resultado; mesma chave com argumento diferente dá `idempotency_conflict`; ferramenta de outro servidor não é exposta.

## Defeitos achados na revisão
1. Dois testes red com defeito (digest incompleto; loja 500 esperando sucesso), corrigidos pelo OPS.
2. Token consumido + erro transitório prendia o cliente: marcador PENDENTE (ADR 0011).
3. Tokens em memória não eram compartilhados entre MCP e orquestrador: adaptadores Postgres (migration 0003). A migration 0001 passou a criar só as tabelas iniciais (`create_all` com o metadata atual colidia com a 0003).

## Riscos / pendências
- Sem `DATABASE_URL`/`POSTGRES_*` explícitos o CLI cai em memória com aviso: falha segura (ações recusadas), mas deve virar erro em produção (Fase 10).
- Tabelas de tokens e idempotência crescem sem purga (job na Fase 09/10).
- `classify_reply` é conservadora: "pode ser" e "isso mesmo" caem em UNCLEAR e o agente repergunta (medir nos evals, Fase 08).
- Teste de timeout real leva ~9 s; `mcp` fixado em `<2` (2.x renomeou FastMCP).
- `list_customer_orders` aplica `limit` no cliente (a loja não tem o parâmetro).
