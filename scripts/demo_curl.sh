#!/usr/bin/env bash
# Conversa de ponta a ponta só com cURL (ADR 0014 e 0020): cria a sessão web, abre o WebSocket
# da conversa, envia a mensagem pelo webhook e mostra a resposta do agente, que atravessou
# Redpanda, worker, grafo de agentes, outbox e WebSocket. Base do GIF do README
# (scripts/record_demo_gif.sh).
#
# Uso: scripts/demo_curl.sh ["mensagem"]
# Variáveis:
#   API_URL             padrão http://localhost:8000
#   CUSTOMER_ID         cliente do seed (padrão C0167, dono do pedido O000001)
#   WEB_SESSION_SECRET  só sem DEMO_MODE: assina a sessão localmente (openssl)
#   REPLY_TIMEOUT_S     espera máxima pela resposta (padrão 30)
#   TYPE_DELAY          segundos por caractere ao "digitar" os comandos (padrão 0)
#   DEMO_NOTE           linha de aviso sob o título (ex.: que as respostas são gravadas)
# Requer: curl com WebSocket (8.x), jq, stdbuf; openssl só para assinar localmente.
set -euo pipefail

API_URL=${API_URL:-http://localhost:8000}
CUSTOMER_ID=${CUSTOMER_ID:-C0167}
REPLY_TIMEOUT_S=${REPLY_TIMEOUT_S:-30}
TYPE_DELAY=${TYPE_DELAY:-0}
MESSAGE=${1:-"Oi! Onde está o meu pedido O000001?"}
WS_URL=${API_URL/http/ws}

bold=$'\e[1m' dim=$'\e[2m' cyan=$'\e[36m' green=$'\e[32m' yellow=$'\e[33m' reset=$'\e[0m'

for tool in curl jq stdbuf; do
  command -v "$tool" > /dev/null || { echo "falta $tool" >&2; exit 2; }
done

step() { printf '\n%s%s%s\n' "$bold$cyan" "$1" "$reset"; }

show() {  # mostra o comando como se fosse digitado
  local text="$ $*"
  if [ "$TYPE_DELAY" = 0 ]; then
    printf '%s%s%s\n' "$yellow" "$text" "$reset"
    return
  fi
  printf '%s' "$yellow"
  for ((i = 0; i < ${#text}; i++)); do
    printf '%s' "${text:i:1}"
    sleep "$TYPE_DELAY"
  done
  printf '%s\n' "$reset"
}

sign_locally() {  # mesmo formato de sign_web_session: base64url(json).hex(hmac_sha256)
  local session_id=$1 claims payload mac
  claims=$(jq -cn --arg c "$CUSTOMER_ID" --arg s "$session_id" \
    '{customer_id: $c, expires_at: (now + 3600 | todate | sub("Z$"; "+00:00")), session_id: $s}')
  payload=$(printf '%s' "$claims" | base64 -w0 | tr '+/' '-_' | tr -d '=')
  mac=$(printf '%s' "$payload" | openssl dgst -sha256 -hmac "$WEB_SESSION_SECRET" -hex | awk '{print $NF}')
  printf '%s.%s' "$payload" "$mac"
}

workdir=$(mktemp -d)
ws_pid=""
cleanup() {
  [ -n "$ws_pid" ] && kill "$ws_pid" 2> /dev/null || true
  rm -rf "$workdir"
}
trap cleanup EXIT

printf '%sCommerceAgents · atendimento de e-commerce com agentes de IA%s\n' "$bold" "$reset"
printf '%scanal web: webhook -> Redpanda -> worker (LangGraph) -> outbox -> WebSocket%s\n' "$dim" "$reset"
[ -n "${DEMO_NOTE:-}" ] && printf '%s%s%s\n' "$yellow" "$DEMO_NOTE" "$reset"

step "1. API no ar"
show "curl -s $API_URL/health"
curl -fsS "$API_URL/health" | jq -C .

step "2. Sessão web do cliente $CUSTOMER_ID"
show "curl -s -X POST $API_URL/demo/session -d '{\"customer_id\": \"$CUSTOMER_ID\"}'"
status=$(curl -sS -o "$workdir/session.json" -w '%{http_code}' -X POST "$API_URL/demo/session" \
  -H 'Content-Type: application/json' -d "{\"customer_id\": \"$CUSTOMER_ID\"}")
if [ "$status" = 200 ]; then
  token=$(jq -r .token "$workdir/session.json")
  conversation_id=$(jq -r .conversation_id "$workdir/session.json")
  jq -C '.token |= .[0:24] + "…"' "$workdir/session.json"
else
  : "${WEB_SESSION_SECRET:?sem DEMO_MODE (HTTP $status), defina WEB_SESSION_SECRET para assinar a sessão}"
  printf '%s(sem modo demonstração: sessão assinada localmente com WEB_SESSION_SECRET)%s\n' "$dim" "$reset"
  session_id="curl-$(date +%s)-$RANDOM"
  token=$(sign_locally "$session_id")
  conversation_id="web:$session_id"
fi
session_id=${conversation_id#web:}
encoded_conversation=${conversation_id/:/%3A}

step "3. WebSocket da conversa (a resposta chega por aqui)"
show "curl -N '$WS_URL/ws/web/$encoded_conversation?token=…'"
stdbuf -o0 curl -sN "$WS_URL/ws/web/$encoded_conversation?token=$token" > "$workdir/ws.out" &
ws_pid=$!
sleep 1

step "4. Mensagem do cliente pelo webhook web"
message_id="msg-$(date +%s)-$RANDOM"
body=$(jq -cn --arg s "$session_id" --arg m "$message_id" --arg t "$MESSAGE" \
  '{session_id: $s, message_id: $m, text: $t}')
show "curl -s -X POST $API_URL/webhooks/web -H 'X-Web-Session: …' -d '{\"text\": \"$MESSAGE\"}'"
started=$(date +%s.%N)
curl -fsS -X POST "$API_URL/webhooks/web" -H 'Content-Type: application/json' \
  -H "X-Web-Session: $token" -d "$body" | jq -C .

step "5. Resposta do agente"
printf '%saguardando...%s' "$dim" "$reset"
deadline=$((SECONDS + REPLY_TIMEOUT_S))
reply=""
while [ $SECONDS -lt $deadline ]; do
  reply=$(jq -c --arg id "reply:$message_id" 'select(.message_id == $id)' "$workdir/ws.out" \
    2> /dev/null | head -n 1 || true)
  [ -n "$reply" ] && break
  sleep 0.2
done
printf '\r\e[K'
if [ -z "$reply" ]; then
  echo "sem resposta em ${REPLY_TIMEOUT_S}s" >&2
  exit 1
fi
elapsed=$(echo "$(date +%s.%N) - $started" | bc)
printf '%s\n' "$reply" | jq -C '{message_id, source}'
printf '\n%s\n' "$(jq -r .text <<< "$reply")" | fold -s -w "${COLUMNS:-100}"
printf '\n%s✔ %s respondeu em %.1f s%s\n' "$green$bold" "$(jq -r .source <<< "$reply")" "$elapsed" "$reset"
