# 0018. Observabilidade com OpenTelemetry (traces, métricas) e Langfuse via OTLP

- Status: Accepted
- Data: 2026-11-10
- Refina: ADR 0009, 0017

## Contexto e problema

A meta da Fase 09 é ter 100% das conversas com trace correlacionado por `conversation_id`,
medir latência (p95 sem LLM < 150 ms; primeira resposta com LLM < 4 s), custo por conversa e o
estado do circuit breaker (ADR 0017). O compose já sobe `otel-collector` (OTLP → Jaeger) e
Langfuse, mas a aplicação não emite nada: só logs de texto. Uma conversa atravessa webhook →
Redpanda → worker → grafo → ferramentas/LLM → outbox → envio, em processos diferentes.

## Opções consideradas

1. OpenTelemetry (API no código, SDK configurado só na composição), exportando por OTLP para o
   collector, que distribui para Jaeger (traces), Prometheus (métricas) e Langfuse (spans de LLM).
2. SDK do Langfuse direto no código para LLM e OTel para o resto: dois modelos de
   instrumentação e duas correlações.
3. Só logs estruturados com `conversation_id`.

## Decisão

Opção 1.

- Dependência só da API `opentelemetry-api` em `infrastructure/` e `interfaces/`; o SDK e os
  exportadores são configurados em `interfaces/` (composição) e só quando
  `OTEL_EXPORTER_OTLP_ENDPOINT` estiver definido. Sem configuração a API é no-op: testes e eval
  não mudam. `domain/` e `application/` não importam OpenTelemetry (contrato import-linter).
- Traces: span raiz por turno (`conversation.turn`), filhos por nó do grafo, por chamada de LLM
  (convenções `gen_ai.*`: sistema, modelo, provider efetivo, tokens, custo) e por ferramenta
  (nome, ok, código de erro, latência). Todos com `conversation_id`, `channel` e `message_id`.
  O contexto de trace viaja nos headers das mensagens do Redpanda (inbound e outbox), para que
  webhook, worker e envio formem um único trace.
- Métricas OTel: histogramas de latência do turno, do LLM e das ferramentas; contadores de
  chamadas de LLM por provider e resultado, aberturas do circuito, uso do fallback, handoffs por
  motivo, tokens e custo. O collector exporta para Prometheus; dashboards Grafana versionados no
  repositório (provisionamento como código).
- Langfuse recebe os spans de LLM pelo endpoint OTLP dele, a partir do collector (credenciais só
  no ambiente do collector).
- Privacidade: por padrão nenhum texto de cliente, prompt, resposta ou argumento de ferramenta vai
  para spans, métricas ou logs, só identificadores e números. `OTEL_CAPTURE_CONTENT=true` liga a
  captura de prompts e respostas em ambiente de desenvolvimento; nunca tokens de confirmação nem
  chaves (ADR 0013). Logs estruturados levam `trace_id` e `conversation_id`.

## Consequências

- Positivas: um trace de ponta a ponta por mensagem; latência, custo e resiliência medidos com o
  mesmo instrumento; troca de backend sem mexer no código.
- Negativas: mais serviços no compose (Prometheus, Grafana); propagação de contexto pelo broker
  precisa de testes; risco de vazar dados pessoais se a captura de conteúdo for ligada fora de
  desenvolvimento.

## Adendo (Fase 09, 2026-11-10): custo por chamada

- O custo vem de `LLMResult.cost_usd` (`None` = desconhecido, nunca um 0 inventado): o `OpenCodeCliProvider` usa o `step_finish` da própria chamada e o `OpenAICompatibleProvider` a tabela de preços, que mora em `infrastructure/llm/pricing.py` + `pricing.yaml` (`evals.pricing` só reexporta). Breaker e fallback preservam custo e provider.
- Telemetria: `gen_ai.usage.cost_usd` no span `llm.complete` e contador `llm.cost.usd{provider, model}` quando o custo é conhecido; `conversation.turn.cost_usd` no span raiz e histograma `conversation.turn.cost{channel}` só se todas as chamadas do turno tiverem custo. Nenhuma métrica de custo leva `conversation_id`.
- Limite: as chamadas do roteador de intenção não passam pelo `TracedLLM` e ficam fora do custo do turno.
