# Orquestrador — contrato (Fase 06)

ADR 0003, 0010, 0013. Tipos: `application/dto/agents.py`, estado: `infrastructure/agents/state.py`.

## Grafo (um turno)
```
START -> ingest -> guard -> {pending_action?} -yes-> confirm -> END
                                    |no
                                 supervisor -> {agent}
   pedidos | catalogo | politicas | pos_venda  -> specialist_loop -> finalize -> END
   geral (ambiguous / injection_guard)         -> template (esclarece/recusa) -> END
   humano (handoff_request / falhas)           -> handoff -> END
```
- `ingest`: dedup por `message_id` (conversa idempotente), `token_budget_remaining`, anexa mensagem como dado.
- `guard`: `detect_injection(text)` -> `injection_flagged`.
- `supervisor`: `IntentRouter.route` -> `Intent` + confiança; mapa fixo intenção -> agente: order_status/list_orders/cancel_order -> pedidos; product_search/availability/shipping_quote -> catalogo; policy_question -> politicas; return_eligibility/return_request -> pos_venda; handoff_request -> humano; ambiguous/injection_guard ou confiança < 0,5 -> geral.
- `specialist_loop`: até 4 passos. Prompt = system do agente (papel, regras, catálogo de ferramentas da allowlist com JSON Schema de `INPUT_MODELS`) + memória do cliente (preferências, como dado) + histórico recente + `<dados_do_cliente>`. LLM responde JSON `ToolCall` ou `FinalAnswer`. `ToolCall` -> `ScopedToolInvoker.invoke(...)` (irreversível -> `ProposeIrreversibleAction` e fim do turno com `awaiting_confirmation`); resultado volta ao LLM como `<dados_ferramenta>`. Ferramentas de cada agente = `AGENT_ALLOWLIST` (chaves de código: pedidos->Pedidos, catalogo->CatalogoVendas, politicas->Politicas, pos_venda->PosVenda).
- `finalize`: `sanitize_reply`, verificação de citações (politicas), grava `policy_citations`, `OutboundReply`.

## Módulos (símbolos exatos)
application/agents/
- `protocol.py`: `parse_agent_action(text: str) -> ToolCall | FinalAnswer` (extrai o primeiro objeto JSON, valida; `ActionParseError` se inválido); `render_tool_catalog(agent_key: str) -> str`.
- `guards.py`: `wrap_untrusted(label: str, text: str) -> str` (escapa delimitadores presentes no texto); `detect_injection(text: str) -> bool`; `sanitize_reply(text: str) -> str`.
- `scoped_invoker.py`: `ScopedToolInvoker(inner: ToolInvoker, customer_id: str)` implementa `ToolInvoker`.
- `replies.py`: funções puras pt-BR: `clarification()`, `refusal()`, `handoff_notice()`, `llm_unavailable()`, `no_source_found()`, `confirmation_outcome(outcome, pending) -> str` (executado, falha, recusado, ambíguo, expirado).
- `turn.py`: `AGENT_FOR_INTENT: dict[Intent, str]`, `AGENT_TOOL_KEY: dict[str, str]`, `MAX_TOOL_STEPS = 4`, `MIN_CONFIDENCE = 0.5`.
infrastructure/agents/
- `router.py`: `LLMIntentRouter(llm)` implementa `IntentRouter` (JSON `{intent, confidence}` validado; qualquer falha -> `AMBIGUOUS` 0.0).
- `graph.py`: `GraphDeps(llm, router, tools: ToolInvoker, tokens: ConfirmationTokenStore, publish_event, clock, memory: CustomerMemory, new_key)` e `build_graph(deps, *, checkpointer) -> CompiledStateGraph`.
- `service.py`: `ConversationService(graph_factory, ...)`: `async handle(event: InboundMessageReceived, customer_id: str) -> OutboundReply` (thread_id = conversation_id; ferramentas escopadas por turno ao `customer_id`).
- `checkpointer.py`: `create_postgres_checkpointer(url)` (langgraph-checkpoint-postgres; `setup()` idempotente).
- `memory.py` + migration 0005: `SqlCustomerMemory(session_factory)` implementa `CustomerMemory` (tabela `customer_preferences(customer_id, key, value, updated_at)`); nesta fase só leitura é usada no prompt.
Handlers internos do ToolExecutor: `search_policies` -> `PolicyRetriever.retrieve`; `request_handoff` -> publica `HandoffRequested`.

## Fora do escopo
Provider real de LLM (adaptador + circuit breaker: Fase 09; adaptador mínimo para o eval real: início da Fase 08). Canais e painel de handoff: Fase 07.
