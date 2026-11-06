## Objetivo
Canais (WhatsApp, Instagram, web), pipeline de mensagens confiável (Redpanda + Transactional Outbox) e handoff humano com painel, sem perder nem duplicar mensagens e sem confiar no texto do cliente para identidade.

## Task Cards cobertos
- Líder: ADR 0014, `docs/architecture/channels.md`, DTOs/ports de canais e handoff
- TASK-07-01 / 01b testes red: assinatura, normalização, sessão web, casos de uso, persistência, broker, API, painel (OPS)
- TASK-07-02/03/04g webhooks, ledger/outbox/relay, handoff, mensageria, API/worker/composição, painel em JS puro (CORE)

## ADRs criados
- 0014 Identidade nos canais, pipeline de mensagens e protocolo de handoff.

## Como verificar
```bash
make lint && make test && make test-panel
make up && make migrate
make run-api        # porta 8000, painel em /panel
make run-worker     # inbound + relay + sender
```

## Métricas
- 826 testes (2 do broker exigem a porta 9092 livre) e 13 testes do painel; cobertura >= 95% nos módulos novos; mypy --strict e 4 contratos import-linter verdes.
- Verificação do Líder de ponta a ponta com Redpanda real: webhook web assinado, 200 imediato, worker, grafo, outbox, relay, WebSocket do cliente recebe a resposta `reply:<message_id>`; token web inválido e assinatura WhatsApp inválida dão 401. Testes do barramento contra um Redpanda em container passam com o do compose parado.

## Defeitos achados na revisão
1. WebSocket web aceitava conexão sem token (qualquer um que soubesse a conversa leria as respostas): exige token de sessão com `session_id` igual ao da conversa (contrato corrigido por achado do CORE).
2. Fake de handoff usava `dataclasses.replace` em modelo Pydantic (teste corrigido pelo OPS).

## Riscos / pendências
- Sem provider de LLM: `UnconfiguredLLM` faz o roteador cair em "preciso entender melhor". O sistema sobe e é seguro, mas só atende de verdade após o provider real (Fase 08).
- Idempotência dos envios WhatsApp/Instagram é em memória por processo: reinício pode duplicar uma mensagem já entregue.
- Token estático do painel (`PANEL_TOKEN`) serve para MVP, não para produção.
- Instagram é anônimo (sem pedidos); verificação por e-mail/pedido fora do escopo.
- Processos locais: API, worker e broker; sem tratamento de partição quente.
- Mistura de commits entre agentes no mesmo checkout (conteúdo correto, histórico não reescrito).
