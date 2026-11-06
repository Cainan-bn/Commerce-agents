# Contrato das ferramentas

Fonte de verdade: `src/commerce_agents/application/dto/tools.py` (schemas Pydantic strict, `TOOL_SPECS`, `AGENT_ALLOWLIST`). Regra de irreversíveis: ADR 0008 + ADR 0011.

| Ferramenta | Servidor | Irrev. | Loja mock | Timeout | Retries |
|---|---|---|---|---|---|
| get_order_status | orders | não | GET /orders/{id} | 3s | 2 |
| list_customer_orders | orders | não | GET /customers/{id}/orders | 3s | 2 |
| cancel_order | orders | sim | POST /orders/{id}/cancel | 5s | 1 |
| search_products | catalog | não | GET /products | 3s | 2 |
| check_availability | catalog | não | GET /products/{id}/availability | 3s | 2 |
| quote_shipping | shipping | não | POST /shipping/quote | 3s | 2 |
| check_return_eligibility | returns | não | GET /returns/eligibility | 3s | 2 |
| open_return | returns | sim | POST /returns | 5s | 1 |
| search_policies | interna (RAG, Fase 05) | não | — | 3s | 1 |
| request_handoff | interna (Fase 07) | não | — | 3s | 0 |

## Mapeamento de erros HTTP da loja → `ToolErrorCode`
| Loja | Código | Retry |
|---|---|---|
| 404 | `not_found` (em `open_return`, SKU fora do pedido também) | não |
| 409 em cancel | `not_cancelable` | não |
| 409 em return | `already_requested` | não |
| 422 em return com `detail` de elegibilidade | `not_eligible` | não |
| 422 `idempotency key reutilizada...` | `idempotency_conflict` | não |
| 422 demais / validação | `invalid_argument` | não |
| timeout | `upstream_timeout` | sim |
| 502/503/504 | `upstream_unavailable` | sim |
| outros 5xx/4xx | `upstream_error` | não |

Erros nunca expõem corpo bruto da loja, URL nem stack. O executor retorna `ToolError` (nunca lança para o agente) e registra `ToolInvoked`.

## Allowlist (ADR 0010)
Pedidos: get_order_status, list_customer_orders, cancel_order, request_handoff. CatalogoVendas: search_products, check_availability, quote_shipping, request_handoff. Politicas: search_policies, check_return_eligibility, request_handoff. PosVenda: get_order_status, check_return_eligibility, open_return, search_policies, request_handoff. Ferramenta fora da allowlist: `not_allowed`, sem chamada.
