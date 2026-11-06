## Objetivo
Orquestrador LangGraph (supervisor + 4 especialistas) com checkpoint no PostgreSQL, em que o LLM só propõe e o código decide o que é crítico: identidade e posse do pedido, pré-checagem e confirmação de ações irreversíveis, citações de política, handoff e limites.

## Task Cards cobertos
- Líder: ADR 0013, `docs/architecture/orchestrator.md`, `AgentState` (agentes e intenções dos cenários, `message_id`), `application/dto/agents.py`; correção dos cenários POS-006/007
- TASK-06-02 / 02b / 02c testes red: protocolo, guardas, router, grafo (unit + Postgres) (OPS)
- TASK-06-03/04/05 protocolo/guardas/respostas/invoker escopado, `LLMIntentRouter`, migration 0005 + `SqlCustomerMemory`, checkpointer, grafo e `ConversationService` (CORE)
- TASK-06-06 revisão de determinismo (Líder), que gerou TASK-06-07r/g: pré-checagem antes de propor ação irreversível

## ADRs criados
- 0013 Protocolo de turno do orquestrador: decisões críticas em código, LLM só propõe.

## Como verificar
```bash
make lint && make test
make up && make migrate     # inclui 0005; checkpointer cria suas tabelas no 1º uso
```

## Métricas
- 687 testes, cobertura 99% (graph 99%, demais módulos novos 100%); mypy --strict e 4 contratos import-linter verdes.
- Integração Postgres: `pending_action` sobrevive a reinício (retomada pelo mesmo `thread_id`), threads isoladas, memória do cliente.

## Defeitos achados na revisão
1. Cenários POS-006/007 com agente incoerente (dado corrigido).
2. Dois testes red com defeito (canal estrito; orçamento de tokens), corrigidos pelo OPS.
3. A proposta de ação irreversível não validava posse nem viabilidade: o cliente era perguntado "Confirma?" para pedido de outro cliente, não cancelável ou fora do prazo. Pré-checagem em código, sem emitir token (06-07).

## Riscos / pendências
- Provider real de LLM e circuit breaker: não há adaptador ainda (Fase 08 para o eval real; resiliência na Fase 09). Tudo aqui foi testado com LLM roteirizado.
- `request_handoff` é interceptado pelo grafo (o `InternalHandler` do executor não recebe `conversation_id`); `search_policies` precisa ser ligado ao `ToolExecutor` na composição (Fase 07).
- Com confirmação pendente, mensagens fora do assunto repetem "não entendi" até expirar (5 min) e a que dispara a expiração é descartada; ajustar com base nos evals.
- Orçamento de tokens só é checado no início do turno; `customer_preferences` só é lida.
- Pre-commit/mypy fica lento com vários agentes no mesmo checkout; commits do Forja e do Nucleo se misturaram duas vezes (conteúdo correto, histórico não reescrito).
