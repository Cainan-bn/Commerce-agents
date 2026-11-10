# Métricas no Prometheus

Nomes exatos que o Prometheus guarda para as métricas OTel do app (ADR 0018). O exporter
`prometheus` do collector converte os nomes: `.` vira `_`, contadores ganham `_total`, histogramas
ganham `_bucket`/`_sum`/`_count` e a unidade entra no nome (`s` vira `_seconds`, `USD` fica como
`_USD`). Atributos com ponto também viram `_` (`tool.name` vira `tool_name`).

Levantados em 2026-11-10 emitindo cada instrumento de
`commerce_agents.infrastructure.telemetry` uma vez via OTLP para
`otel/opentelemetry-collector-contrib:0.164.0` e lendo `localhost:8889/metrics`.
Dashboards e alertas só podem usar os nomes desta tabela (verificado em
`tests/unit/infra/test_dashboards_e_alertas.py`).

| Métrica OTel | Tipo | Séries no Prometheus | Labels do app |
|---|---|---|---|
| `conversation.turn.duration` | histograma (s) | `conversation_turn_duration_seconds_bucket`, `conversation_turn_duration_seconds_sum`, `conversation_turn_duration_seconds_count` | `channel` |
| `conversation.turn.cost` | histograma (USD) | `conversation_turn_cost_USD_bucket`, `conversation_turn_cost_USD_sum`, `conversation_turn_cost_USD_count` | `channel` |
| `llm.calls` | contador | `llm_calls_total` | `provider`, `outcome` |
| `llm.duration` | histograma (s) | `llm_duration_seconds_bucket`, `llm_duration_seconds_sum`, `llm_duration_seconds_count` | `provider` |
| `llm.tokens` | contador | `llm_tokens_total` | `provider`, `direction` |
| `llm.cost.usd` | contador (USD) | `llm_cost_usd_USD_total` | `provider`, `model` |
| `llm.circuit.opened` | contador | `llm_circuit_opened_total` | `provider` |
| `llm.fallback.used` | contador | `llm_fallback_used_total` | `provider` |
| `handoff.requested` | contador | `handoff_requested_total` | `reason` |
| `tool.duration` | histograma (s) | `tool_duration_seconds_bucket`, `tool_duration_seconds_sum`, `tool_duration_seconds_count` | `tool_name`, `tool_ok` |

Labels de recurso (`service_name`, `exported_job`, `exported_instance`, `otel_scope_name`...) vêm
da conversão de recurso do collector. Nenhuma métrica leva `conversation_id`, `customer_id` ou
`message_id`.
