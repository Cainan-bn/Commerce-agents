#!/usr/bin/env bash
# Orquestra a carga da Fase 09 (TASK-09-05): sobe stub do LLM, loja fake, API e worker a partir de
# APP_DIR, roda um cenário k6, amostra CPU/memória e coleta Prometheus + stub em $OUT.
#
# Uso: load/run.sh <webhook|conversa|caos|trace>
# Requer: infraestrutura do compose no ar (postgres, redpanda, otel-collector, prometheus, jaeger),
# banco migrado e com seed (make migrate seed-db), k6 no PATH.
# Variáveis: APP_DIR (padrão: raiz do repo; use um worktree limpo), OUT, VUS, RAMP, HOLD,
# PACING_S, RATE_PER_MIN, DURATION, CHAOS_AT, CHAOS_FOR_S, REPLY_TIMEOUT_S, LLM_STUB_LATENCY_MS,
# LLM_STUB_JITTER_MS, METRICS_WAIT_S, FALLBACK=1 (2º stub como LLM_FALLBACK_*). Ver load/README.md.
set -euo pipefail

SCENARIO=${1:?uso: load/run.sh <webhook|conversa|caos|trace>}
LOAD_DIR=$(cd "$(dirname "$0")" && pwd)
APP_DIR=$(cd "${APP_DIR:-$LOAD_DIR/..}" && pwd)
OUT=${OUT:-$LOAD_DIR/results/$(date +%Y%m%d-%H%M%S)-$SCENARIO}
REDPANDA_CONTAINER=${REDPANDA_CONTAINER:-commerce-agents-redpanda-1}
PROMETHEUS_URL=${PROMETHEUS_URL:-http://localhost:9090}
STUB_PORT=${LLM_STUB_PORT:-8090}
STUB_URL="http://127.0.0.1:$STUB_PORT"
METRICS_WAIT_S=${METRICS_WAIT_S:-80}
mkdir -p "$OUT"

# Ambiente da aplicação: só valores de teste local (o stub não aceita chave real).
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL="$STUB_URL/v1"
export LLM_API_KEY=stub-sem-segredo  # pragma: allowlist secret
export LLM_MODEL=stub-model
export STORE_BASE_URL=http://127.0.0.1:8001
export KAFKA_BOOTSTRAP=${KAFKA_BOOTSTRAP:-localhost:9092}
export WEB_SESSION_SECRET=${WEB_SESSION_SECRET:-carga-local-nao-e-segredo}  # pragma: allowlist secret
export PANEL_TOKEN=${PANEL_TOKEN:-carga-local}  # pragma: allowlist secret
export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}
export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-commerce-agents}
export LOG_LEVEL=${LOG_LEVEL:-WARNING}
export LLM_STUB_PORT=$STUB_PORT
export LLM_STUB_LATENCY_MS=${LLM_STUB_LATENCY_MS:-800}
export LLM_STUB_JITTER_MS=${LLM_STUB_JITTER_MS:-100}
FALLBACK=${FALLBACK:-0}
FALLBACK_PORT=${LLM_FALLBACK_STUB_PORT:-8091}
if [ "$FALLBACK" = 1 ]; then
  # Secundário (ADR 0017): outro stub, que o caos não derruba.
  export LLM_FALLBACK_PROVIDER=openai-compatible
  export LLM_FALLBACK_MODEL=stub-fallback-model
  export LLM_FALLBACK_BASE_URL="http://127.0.0.1:$FALLBACK_PORT/v1"
  export LLM_FALLBACK_API_KEY=stub-sem-segredo  # pragma: allowlist secret
fi

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  (cd "$APP_DIR" && uv sync --frozen --quiet)
fi
PY="$APP_DIR/.venv/bin/python"
PIDS="$OUT/pids"
: > "$PIDS"

start() {  # start <nome> <comando...>: processo direto (sem uv), pid real para o ps
  local name=$1
  shift
  (cd "$APP_DIR" && exec "$@" > "$OUT/$name.log" 2>&1) &
  echo "$name $!" >> "$PIDS"
}

wait_http() {  # wait_http <url> <segundos>
  local deadline=$((SECONDS + $2))
  until curl -sf -o /dev/null "$1"; do
    if [ $SECONDS -ge $deadline ]; then
      echo "[load] $1 não respondeu em $2 s" >&2
      return 1
    fi
    sleep 1
  done
}

# shellcheck disable=SC2329  # chamada pelo trap EXIT abaixo
stop_all() {
  while read -r name pid; do
    kill "$pid" 2> /dev/null || true
  done < "$PIDS"
  wait 2> /dev/null || true
}
trap stop_all EXIT

# Banco na migração do código medido (idempotente, como `make migrate`).
(cd "$APP_DIR" && "$PY" -c "from commerce_agents.infrastructure.persistence.migrate import \
sync_url_from_env, upgrade_to_head; upgrade_to_head(sync_url_from_env())") > "$OUT/migrate.log" 2>&1

start stub "$PY" "$LOAD_DIR/stub_llm/server.py"
if [ "$FALLBACK" = 1 ]; then
  LLM_STUB_PORT=$FALLBACK_PORT start stub_fallback "$PY" "$LOAD_DIR/stub_llm/server.py"
fi
start mock "$PY" -m uvicorn mock_store.main:app --port 8001 --log-level warning
start api "$PY" -m uvicorn commerce_agents.interfaces.main:app --port 8000 --log-level warning
wait_http "$STUB_URL/health" 30
if [ "$FALLBACK" = 1 ]; then wait_http "http://127.0.0.1:$FALLBACK_PORT/health" 30; fi
wait_http http://127.0.0.1:8001/orders/O000001 60
wait_http http://127.0.0.1:8000/health 60

if [ "$SCENARIO" = webhook ]; then
  # Mede só o gateway: worker parado; depois o grupo pula o que foi enfileirado.
  RESOURCE_NAMES=(api)
else
  start worker "$PY" -m commerce_agents.interfaces.worker all
  RESOURCE_NAMES=(api worker stub)
  # Aquecimento: o worker anterior pode não ter saído do grupo de consumo; espera o rebalance
  # até uma mensagem de teste receber resposta, para a espera não entrar na medição.
  for attempt in 1 2 3 4 5 6; do
    if "$PY" "$LOAD_DIR/scripts/check_trace.py" --probe-only --out /dev/null \
      >> "$OUT/warmup.log" 2>&1; then
      break
    fi
    [ "$attempt" -lt 6 ] || { echo "[load] aquecimento falhou (ver warmup.log)" >&2; exit 1; }
  done
  "$PY" "$LOAD_DIR/scripts/check_trace.py" --probe-only --out /dev/null >> "$OUT/warmup.log" 2>&1
  curl -sf -X POST "$STUB_URL/admin/reset" > /dev/null
  if [ "$FALLBACK" = 1 ]; then
    curl -sf -X POST "http://127.0.0.1:$FALLBACK_PORT/admin/reset" > /dev/null
    RESOURCE_NAMES+=(stub_fallback)
  fi
fi

"$LOAD_DIR/scripts/sample_resources.sh" "$PIDS" "$OUT" 5 &
SAMPLER=$!
date +%s > "$OUT/start_ts"
K6=(k6 run --quiet --summary-trend-stats "avg,min,med,max,p(90),p(95),p(99)"
  --summary-export "$OUT/k6-summary.json" -e WEB_SESSION_SECRET="$WEB_SESSION_SECRET"
  -e STUB_URL="$STUB_URL")
for var in BASE_URL VUS RAMP HOLD PACING_S RATE_PER_MIN DURATION PRE_VUS MAX_VUS CHAOS_AT \
  CHAOS_FOR_S REPLY_TIMEOUT_S; do
  if [ -n "${!var:-}" ]; then K6+=(-e "$var=${!var}"); fi
done

status=0
case "$SCENARIO" in
  webhook | conversa | caos)
    (cd "$LOAD_DIR/k6" && "${K6[@]}" "$SCENARIO.js") 2>&1 | tee "$OUT/k6.log" || status=$?
    ;;
  trace)
    "$PY" "$LOAD_DIR/scripts/check_trace.py" --out "$OUT/trace.json" || status=$?
    ;;
  *)
    echo "[load] cenário desconhecido: $SCENARIO" >&2
    exit 2
    ;;
esac
date +%s > "$OUT/end_ts"
kill "$SAMPLER" 2> /dev/null || true

if [ "$SCENARIO" = webhook ]; then
  # O worker não subiu: o grupo está vazio e pode pular o que o cenário enfileirou.
  docker exec "$REDPANDA_CONTAINER" rpk group seek inbound-worker --to end > "$OUT/seek.log" 2>&1 \
    || echo "[load] aviso: seek do grupo inbound-worker falhou (ver seek.log)" >&2
fi

if [ "$SCENARIO" != trace ]; then
  echo "[load] aguardando ${METRICS_WAIT_S}s (export OTel 60 s + scrape 15 s)"
  sleep "$METRICS_WAIT_S"
  "$PY" "$LOAD_DIR/scripts/collect.py" --out "$OUT/results.json" --prometheus "$PROMETHEUS_URL" \
    --stub "$STUB_URL" --start "$(cat "$OUT/start_ts")" --end "$(cat "$OUT/end_ts")" \
    --k6-summary "$OUT/k6-summary.json" --resources "$OUT/resources.csv" \
    --docker "$OUT/docker.csv" --names "${RESOURCE_NAMES[@]}"
  if [ "$FALLBACK" = 1 ]; then
    curl -sf "http://127.0.0.1:$FALLBACK_PORT/admin/stats" > "$OUT/stub_fallback_stats.json" || true
  fi
fi
echo "[load] resultados em $OUT (k6 status $status)"
exit "$status"
