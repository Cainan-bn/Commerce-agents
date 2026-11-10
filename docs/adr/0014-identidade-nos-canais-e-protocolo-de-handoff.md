# 0014. Identidade nos canais, pipeline de mensagens e protocolo de handoff

- Status: Accepted
- Data: 2026-11-06
- Refina: ADR 0006, 0010, 0013

## Contexto e problema

Três canais (WhatsApp, Instagram, web) entregam mensagens duplicadas e fora de ordem, com graus de identificação muito diferentes. O orquestrador exige `customer_id` confiável (ADR 0013). O handoff precisa tirar o agente de IA da conversa e devolver o controle depois, sem perder mensagens.

## Decisão

**Identidade.** `customer_id` só vem de identificação do canal, nunca do texto:
- WhatsApp: o número `from` é autenticado pela Meta (assinatura HMAC do webhook); `IdentityResolver` busca o cliente pelos dígitos do telefone.
- Web: a loja emite um token de sessão HMAC (`session_id`, `customer_id`, expiração) que o widget envia; assinatura inválida/expirada → 401.
- Instagram: o remetente não é mapeável a um cliente da loja → conversa **anônima** (`customer_id = ""`).
- Conversa anônima só usa catálogo, frete e políticas; intenções que exigem pedido (order_status, list_orders, cancel_order, return_*) recebem resposta fixa pedindo para usar o WhatsApp cadastrado ou o site logado. Verificação por e-mail/pedido fica fora do escopo.
- `conversation_id = f"{channel}:{external_id}"` (uma conversa aberta por usuário e canal).

**Webhooks.** Verificam assinatura (`X-Hub-Signature-256`, HMAC-SHA256 do corpo bruto, comparação em tempo constante) ANTES de ler o JSON; normalizam para `InboundMessageReceived` (ignorando eventos que não são texto: status, reações, mídia → 200 sem processar); publicam no tópico `inbound.messages` com chave `conversation_id` e respondem 200 sem esperar o agente. Verificação de desafio GET do WhatsApp/Instagram (`hub.verify_token`) incluída.

**Consumidor (at-least-once, efeito exatamente-uma-vez).** Tabela `inbound_messages(message_id PK, conversation_id, status received|done, reply_json, ...)`. Fluxo: `claim(message_id)` com INSERT ... ON CONFLICT DO NOTHING; se já `done` → não reprocessa (e garante que o outbox tenha a resposta); se `received` (queda anterior) → reprocessa (o grafo deduplica por `message_id` e devolve a mesma resposta). Ao terminar, numa transação: `status=done` + linha no `outbox` (`UNIQUE(inbound_message_id)`); só então o offset é confirmado. O relay publica `outbound.messages` e marca `published_at`. Entregas ao canal (`ChannelSender`) são idempotentes pelo `message_id` de saída.

**Handoff.** O nó `handoff` do grafo publica `HandoffRequested`; o caso de uso `RequestHandoff` persiste `handoffs` (open), muda a conversa para `handoff` e notifica o painel por WebSocket. Com a conversa em `handoff`: mensagens do cliente são gravadas e encaminhadas ao painel, o agente de IA NÃO responde e o cliente recebe uma única confirmação por handoff. O atendente (painel, token estático `PANEL_TOKEN` no MVP) assume (`claim`), responde (vira `OutboundMessageReady` com `source=human`) e encerra (`close`), devolvendo a conversa a `open`. Resumo estruturado: cliente, intenção, motivo e as últimas 6 mensagens.

## Consequências

- Positivas: sem dual-write, sem perda de mensagem em queda do consumidor, identidade não forjável por texto.
- Negativas: instagram sem pedidos no MVP; token estático do painel não serve para produção (ADR futuro com SSO); três processos locais (api, worker, broker).

## Adendo (Fase 09, 2026-11-10): envio idempotente durável e purga periódica

- A idempotência dos senders deixou de ser um conjunto em memória do processo: o port `DeliveryLedger` (Postgres, tabela `delivered_messages(message_id PK, channel, delivered_at)`, migração 0007) é consultado antes do envio e marcado só após sucesso do canal (`INSERT ... ON CONFLICT DO NOTHING`). Reinício ou réplica do worker não reenvia uma resposta já entregue; 4xx e falha final não marcam, então a mensagem pode ser reentregue depois.
- Risco residual: uma queda entre o 2xx do canal e a marcação ainda pode duplicar um envio (janela estreita, at-least-once).
- Modo `purge` do worker (incluso em `all`): a cada `PURGE_INTERVAL_S` (padrão 3600) apaga, com corte `agora - RETENTION_DAYS` (padrão 30), tokens de confirmação usados/expirados (um token ainda válido nunca sai), registros de idempotência e entregas. Falha numa purga é logada e não derruba as outras.
