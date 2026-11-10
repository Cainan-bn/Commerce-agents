## Objetivo
Fazer o atendimento sobreviver à queda do provider de LLM, medir tudo com OpenTelemetry (traces de ponta a ponta, métricas, custo), tornar o envio aos canais idempotente entre reinícios, limpar dados de confirmação antigos e medir carga e caos contra as metas de `docs/architecture/quality-targets.md`.

## Task Cards cobertos
- Líder: ADR 0017 (circuit breaker, fallback, degradação) com adendos (queda do LLM no roteador, contexto no outbox); ADR 0018 (OpenTelemetry, Langfuse via OTLP) com adendos; ADR 0019 (resultados de carga e gargalos).
- TASK-09-01/02 caos do provider e da loja; circuit breaker e fallback; queda da loja na checagem de posse não vira "pedido não encontrado".
- TASK-09-03 traces e métricas OTel; Prometheus e Grafana no compose; 09-03c/d custo por chamada; Langfuse opcional; 09-03e buckets dos histogramas; 09-03f roteador degrada para humano e trace atravessa o outbox.
- TASK-09-07 ledger de entregas durável (`delivered_messages`) e purga periódica de tokens, idempotência e entregas.
- TASK-09-04 dashboards e alertas como código.
- TASK-09-05 k6 (webhook, conversa, caos), LLM simulado, verificação do trace no Jaeger, relatório em `load/reports/`.
- TASK-09-08 novas tentativas só no último provider da cadeia (ADR 0019).
- Gate unit: 161 testes de domínio estavam fora do `-m unit` (e do CI) desde a Fase 01; agora todo teste sob `tests/unit` roda, com teste de guarda.

## ADRs
- 0017 Resiliência do provider de LLM (+ adendos).
- 0018 Observabilidade com OpenTelemetry (+ adendos: custo, outbox, Langfuse opcional, buckets, dashboards).
- 0019 Resultados de carga e caos e decisões sobre os gargalos.
- Adendo ao 0014: envio idempotente durável e purga.

## Como verificar
```bash
make lint && make test-unit && make test-integration
make eval-ci
make up && make load            # ver load/README.md (stub de LLM, k6)
make load-caos-fallback
make up-langfuse                # opcional, exige LANGFUSE_OTLP_AUTH
```
Grafana em http://localhost:3001 (dashboards provisionados), Jaeger em http://localhost:16686.

## Métricas (load/reports/20261110-fase09.md; máquina de 2 núcleos, k6 na mesma máquina, LLM simulado ~800 ms)
| Meta | Medido |
|---|---|
| Webhook p95 < 150 ms | 24,5 ms a 38 req/s; 89,6 ms a 88 req/s; 201,7 ms a 148 req/s (um processo) |
| Primeira resposta p95 < 4 s | 3,10 s (k6); turno p95 2,96 s (Prometheus) |
| Queda do provider | 0 sem resposta, 0 5xx; sem secundário 23 handoffs `llm_indisponivel`; com secundário 0 handoffs |
| Caos com secundário (antes → depois do 09-08) | p95 30,85 → 7,32 s; circuito abre 41,4 → 7,3 s |
| Trace | 1 trace com 8 saltos, webhook → `channel.send` |
| Custo por conversa | ~US$ 0,0076 (eval completo com o modelo real, 54 conversas) |

1149 testes unitários; integração 130 passed; mypy --strict e 5 contratos import-linter verdes; gate de eval por replay aprovado com o cassete inalterado.

## Defeitos achados na revisão
1. Buckets padrão do SDK (escala de ms) com métricas em segundos: todo p95 < 5 s saía 4,75 s e o alerta de 4 s dispararia sempre.
2. Roteador transformava queda do LLM em `ambiguous`: o cliente recebia pedidos de esclarecimento em loop e nunca chegava a humano.
3. Trace partido no outbox: a entrega abria trace novo sem `conversation_id`.
4. Alerta de circuito aberto não via a primeira abertura (série nasce em 1).
5. Novas tentativas do primário antes do fallback (~8 s por chamada).
6. 161 testes de domínio fora do gate unit e do CI.
7. `traceparent` esperado no teste com flags fixas `01` (o SDK gera `03`): corrigido o teste, não a produção.

## Riscos / pendências
- Worker processa uma mensagem por vez e o tópico tem uma partição; API num processo. Escala por partições e réplicas na Fase 10 (ADR 0019).
- Queda entre o 2xx do canal e a marcação no ledger ainda pode duplicar um envio (adendo do ADR 0014).
- Custo por conversa vem do eval, não de tráfego real; publicar no README na Fase 10.
- Harness de eval monta o roteador sem instrumentação (sem efeito no cassete).
- Métrica de custo exposta como `llm_cost_usd_USD_total` (nome redundante, funcional).
- Herdados da Fase 08: lacunas do agente vistas no holdout, INJ-006, contrato AMB, provider de LLM de produção.
