# 0006. Redpanda (API Kafka) e Transactional Outbox

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Webhooks chegam fora de ordem e duplicados. Respostas devem ser publicadas de forma confiável sem dual-write entre banco e broker.

## Opções consideradas

1. Redpanda + Transactional Outbox.
2. Kafka completo.
3. Redis Streams / fila em Postgres.

## Decisão

Opção 1. Redpanda fala a API Kafka com operação simples (binário único, sem ZooKeeper). Mensagens de entrada são particionadas por `conversation_id`, garantindo ordem por conversa. A idempotência usa deduplicação por `message_id`. Eventos de saída são gravados na tabela `outbox` na mesma transação do estado e publicados por um relay.

## Consequências

- Positivas: ordem por conversa, entrega at-least-once com deduplicação, migração fácil para Kafka.
- Negativas: mais um componente na stack local (consome memória no WSL2).
