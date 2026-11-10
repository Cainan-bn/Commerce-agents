# Carga, caos e trace ponta a ponta (Fase 09)

Mede as metas de sistema de `docs/architecture/quality-targets.md` com k6, um LLM simulado
(`stub_llm/`) e a aplicação real (API, worker, loja fake). Nada em `src/` muda para a carga: a
aplicação usa `LLM_PROVIDER=openai-compatible` apontado para o stub.

| Cenário | O que mede | Meta |
|---|---|---|
| `webhook` | `POST /webhooks/web` até a mensagem enfileirada no broker (worker parado) | p95 < 150 ms |
| `conversa` | primeira resposta ao cliente: POST até a resposta chegar no WebSocket da conversa, stub a ~800 ms | p95 < 4 s |
| `caos` | a mesma carga com o LLM fora do ar no meio do run | circuito abre, handoffs crescem, toda mensagem tem resposta, API sem 5xx |
| `trace` | uma mensagem com o sistema ocioso, conferida pela API do Jaeger | um único trace do webhook ao `channel.send` |

## Como rodar

1. Infraestrutura e dados (uma vez):

   ```bash
   docker compose up -d postgres redpanda otel-collector jaeger prometheus grafana
   make migrate seed-db
   ```

2. Rode a aplicação de um worktree limpo do commit que vai ser medido (não do working tree
   compartilhado):

   ```bash
   git worktree add /tmp/ca-carga origin/fase/09-resiliencia-observabilidade-carga
   make load APP_DIR=/tmp/ca-carga SCENARIO=all     # ou webhook, conversa, caos, trace
   ```

   `load/run.sh` sobe stub (8090), loja fake (8001), API (8000) e, fora do cenário `webhook`, o
   worker. Cada run grava em `load/results/<data>-<cenário>/` (fora do git): logs dos processos,
   `k6-summary.json`, `resources.csv` (ps a cada 5 s), `docker.csv` (docker stats) e
   `results.json` (k6 + Prometheus + stub + CPU/memória resumidos).

3. O relatório da fase vai em `load/reports/<data>-fase09.md`, só com números medidos.

## Variáveis

| Variável | Padrão | Uso |
|---|---|---|
| `APP_DIR` | raiz do repositório | código da aplicação que roda (use um worktree limpo) |
| `VUS`, `RAMP`, `HOLD`, `PACING_S` | 50, 30s, 60s, 0.2 | rampa do `webhook` |
| `RATE_PER_MIN`, `DURATION` | 12, 5m | conversas novas por minuto e duração (`conversa`, `caos`) |
| `CHAOS_AT`, `CHAOS_FOR_S` | 90s, 120 | quando o stub cai e por quanto tempo (`caos`) |
| `REPLY_TIMEOUT_S` | 30 | espera máxima pela resposta no WebSocket |
| `LLM_STUB_LATENCY_MS`, `LLM_STUB_JITTER_MS` | 800, 100 | latência do stub |
| `FALLBACK` | 0 | `1` sobe um 2º stub (porta 8091) como `LLM_FALLBACK_*`; o caos só derruba o primário |
| `METRICS_WAIT_S` | 80 | espera antes de ler o Prometheus (export OTel a cada 60 s + scrape de 15 s) |

O stub também aceita `LLM_STUB_FAIL_RATE` (fração de 500) e `LLM_STUB_DOWN=1` (tudo 503) no
ambiente, e muda em tempo de execução por `POST /admin/mode` (`{"down": true}`); `GET
/admin/stats` devolve contagens, trocas de modo e o instante de cada 503.

## Limites conhecidos

- **Canal medido:** os senders do WhatsApp e do Instagram têm a URL da Graph API fixa no código, e
  apontá-los para um sink exigiria mudar `src/`. A carga usa o canal web: a resposta chega pelo
  WebSocket da conversa, que serve de sink e conta a resposta de cada `message_id`.
- **Uma conversa por iteração:** com handoff ativo, só a primeira mensagem da conversa recebe o
  aviso ao cliente (as seguintes vão ao painel). Por isso cada iteração abre uma sessão nova.
- **Worker serial:** `inbound.messages` tem uma partição, então um único consumidor processa uma
  mensagem por vez. A vazão do atendimento é limitada por isso, não pela API.
- **Percentis do Prometheus:** valem desde os buckets do 09-03e (antes, qualquer turno abaixo de
  5 s virava p95 = 4,75 s). A latência da primeira resposta vem do k6, medida no cliente. Contadores
  que nascem já em 1 (circuito, fallback) não aparecem em `increase()`: use o valor bruto por
  instância (cada run sobe um worker novo).
- **Máquina:** WSL2 com Docker Desktop; aplicação, k6 e containers dividem a mesma máquina. Os
  números valem para comparação entre runs, não como capacidade de produção.
