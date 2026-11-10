// Funções comuns dos cenários de carga (TASK-09-05): sessão web assinada, envio e espera da
// resposta pelo WebSocket da conversa. Variáveis: BASE_URL, WEB_SESSION_SECRET, REPLY_TIMEOUT_S.
import crypto from 'k6/crypto';
import encoding from 'k6/encoding';
import http from 'k6/http';
import ws from 'k6/ws';

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const WS_URL = BASE_URL.replace(/^http/, 'ws');
const SECRET = __ENV.WEB_SESSION_SECRET;
const REPLY_TIMEOUT_MS = Number(__ENV.REPLY_TIMEOUT_S || 30) * 1000;

if (!SECRET) {
  throw new Error('defina WEB_SESSION_SECRET (o mesmo da API)');
}

// Pares (cliente, pedido) do seed: o cliente é dono do pedido, então get_order_status responde.
export function seedPairs(path) {
  return open(path)
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => {
      const order = JSON.parse(line);
      return [order.customer_id, order.order_id];
    });
}

export function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function uniqueId(prefix) {
  return `${prefix}-${__VU}-${__ITER}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

// Mesmo formato de `sign_web_session` (ADR 0014): base64url(json).hex(hmac_sha256).
export function newSession(customerId) {
  const sessionId = uniqueId('load');
  const claims = JSON.stringify({
    customer_id: customerId,
    expires_at: '2030-01-01T00:00:00+00:00',
    session_id: sessionId,
  });
  const payload = encoding.b64encode(claims, 'rawurl');
  return { sessionId, token: `${payload}.${crypto.hmac('sha256', SECRET, payload, 'hex')}` };
}

export function postMessage(session, text) {
  const messageId = uniqueId('msg');
  const response = http.post(
    `${BASE_URL}/webhooks/web`,
    JSON.stringify({ session_id: session.sessionId, message_id: messageId, text }),
    {
      headers: { 'Content-Type': 'application/json', 'X-Web-Session': session.token },
      tags: { name: 'webhook' },
    },
  );
  return { messageId, response };
}

// Abre o WebSocket da conversa, envia a mensagem e espera `reply:<message_id>`.
// Devolve { response, messageId, latencyMs, reply } (reply null se não chegou no prazo).
export function converse(session, text) {
  const conversationId = encodeURIComponent(`web:${session.sessionId}`);
  const url = `${WS_URL}/ws/web/${conversationId}?token=${encodeURIComponent(session.token)}`;
  const result = { response: null, messageId: null, latencyMs: null, reply: null };
  ws.connect(url, { tags: { name: 'ws_web' } }, (socket) => {
    let sentAt = 0;
    socket.on('open', () => {
      const posted = postMessage(session, text);
      sentAt = Date.now();
      result.response = posted.response;
      result.messageId = posted.messageId;
      if (posted.response.status !== 200) {
        socket.close();
      }
    });
    socket.on('message', (raw) => {
      const event = JSON.parse(raw);
      if (event.type === 'message' && event.message_id === `reply:${result.messageId}`) {
        result.latencyMs = Date.now() - sentAt;
        result.reply = event;
        socket.close();
      }
    });
    socket.setTimeout(() => socket.close(), REPLY_TIMEOUT_MS);
  });
  return result;
}
