# Canais, pipeline e handoff — contrato (Fase 07)

ADR 0006, 0014. Tipos: `application/dto/channels.py`, `application/ports/channels.py`, `ports/messaging.py`.

## Fluxo
```
Webhook (api) --verifica HMAC--> normaliza --> Redpanda inbound.messages (key=conversation_id) --200
Worker: consome -> InboundLedger.claim -> [conversa em handoff? -> encaminha ao painel]
        -> IdentityResolver -> ConversationService.handle -> ledger.complete(+outbox, mesma txn) -> commit offset
Relay:  outbox -> Redpanda outbound.messages
Sender: consome outbound.messages -> ChannelSender.send (whatsapp|instagram|web), idempotente por message_id
Handoff: grafo publica HandoffRequested -> RequestHandoff (persiste, conversa=handoff, notifica painel por WS)
         painel: claim / reply (vira OutboundMessageReady source=human) / close (conversa volta a open)
```

## interfaces/ (FastAPI; só adapta, sem regra de negócio)
- `interfaces/api.py`: `create_app(deps) -> FastAPI`; rotas: `GET /health`, `GET/POST /webhooks/whatsapp`, `GET/POST /webhooks/instagram`, `POST /webhooks/web`, `GET /panel` (HTML estático), `GET /api/handoffs`, `POST /api/handoffs/{id}/claim|reply|close`, `GET /api/handoffs/{id}/messages`, `WS /ws/panel`, `WS /ws/web/{conversation_id}?token=<sessão web>` (token HMAC válido e `session_id` do token igual ao identificador da conversa `web:<session_id>`; senão fecha com 1008: sem isso qualquer um que conheça o id leria as respostas de outro cliente). Painel e `/api/handoffs*` exigem `Authorization: Bearer <PANEL_TOKEN>` (WS: `?token=`); sem/errado → 401/1008.
- `interfaces/webhooks/{signature,whatsapp,instagram,web}.py`: `verify_signature(secret: str, body: bytes, header: str | None) -> bool` (sha256=<hex>, `hmac.compare_digest`; header ausente/malformado → False); `normalize_whatsapp(payload: dict) -> list[InboundMessageReceived]`, `normalize_instagram(payload: dict) -> list[InboundMessageReceived]` (só texto; ignora status/reação/mídia/eco; `message_id` = id da Meta; `customer_external_id` = telefone só dígitos / IGSID; `text` truncado a 4000); `sign_web_session(secret, session_id, customer_id, expires_at) -> str` e `verify_web_session(secret, token, now) -> WebSession | None` (HMAC-SHA256, formato `base64url(json).hex(hmac)`, expiração).
- Payloads: WhatsApp Cloud API `entry[].changes[].value.messages[]{id, from, timestamp(epoch s), type:"text", text:{body}}`; Instagram `entry[].messaging[]{sender:{id}, timestamp(ms), message:{mid, text, is_echo?}}`; web `{session_id, message_id, text}` + header `X-Web-Session`.
- `interfaces/worker.py`: `python -m commerce_agents.interfaces.worker [inbound|relay|sender|all]`.

## application/
- `use_cases/handle_inbound.py`: `HandleInboundMessage(ledger, identity, service, handoffs, forward_to_panel, clock)` → `async execute(event) -> OutboundMessageReady | None`. Ordem: `ledger.claim`; `done` → `None`; conversa em handoff ativo → grava `HandoffMessage(author=customer)`, notifica painel, 1ª vez devolve confirmação `system`, depois `None`; senão resolve `customer_id` (`""` se anônimo) e chama `service.handle`; converte `OutboundReply` em `OutboundMessageReady(message_id=f"reply:{event.message_id}", source="agent")`; `ledger.complete`. Qualquer exceção NÃO completa o ledger (permite retry).
- `use_cases/request_handoff.py`: `RequestHandoff(handoffs, conversations, notifier, clock, new_id)` → `execute(event: HandoffRequested) -> HandoffRecord` (idempotente: já existe ativo → devolve o existente; muda `Conversation` com `request_handoff`; notifica). `HumanReply`: `reply_as_human(handoff_id, agent, text) -> OutboundMessageReady` (só `claimed`; grava `HandoffMessage(agent_human)`); `ClaimHandoff`, `CloseHandoff` (devolve conversa a `open`: domínio ganha `Conversation.resume(at)`).
- `ConversationService.handle(event, customer_id)` já existe (Fase 06). Anônimo (`customer_id == ""`): intenções de pedido/devolução recebem `replies.identification_required()` no grafo, sem chamar ferramentas.

## infrastructure/
- `persistence`: migration 0006 `inbound_messages`, `outbox` (id, topic, key, payload_json, inbound_message_id UNIQUE nullable, created_at, published_at), `handoffs`, `handoff_messages`; adapters `SqlInboundLedger`, `SqlOutboxRepository` (implementa `OutboxRepository`) + `SqlOutboxRelay(session_factory, bus)`, `SqlHandoffRepository`, `SqlIdentityResolver` (customers.phone por dígitos).
- `messaging/`: `KafkaEventBus` (aiokafka producer, `acks=all`, chave=conversation_id), `consume(topic, group, handler)` com commit manual após o handler, `topics.py`; sender adapters `WhatsAppSender`, `InstagramSender` (httpx → Graph API, token por env; erros 4xx não repetem, 5xx/timeout repetem) e `WebSocketSender` (hub em memória por `conversation_id`).
- `HandoffNotifier` WebSocket: `PanelHub` (conexões do painel; `notify(HandoffRequested)` e novas mensagens).
- Config por env: `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_VERIFY_TOKEN`, `INSTAGRAM_ACCESS_TOKEN`, `WEB_SESSION_SECRET`, `PANEL_TOKEN`, `KAFKA_BOOTSTRAP` (já no `.env.example`).

## Painel (`panel/`, estático)
HTML + JS (ES modules), sem build: lista handoffs ativos ao vivo (WS), abre transcrição, assumir, responder, encerrar. Testes de componentes com `node --test` + jsdom (`make test-panel`).
