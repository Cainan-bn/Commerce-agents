// Cenário conversa (meta: primeira resposta com LLM, p95 < 4 s). Carga sustentada em taxa
// constante (RATE_PER_MIN conversas novas por minuto, DURATION); stub do LLM a ~800 ms.
// A latência medida é do POST até a resposta chegar no WebSocket da conversa.
import { check } from 'k6';
import { SharedArray } from 'k6/data';
import { Counter, Rate, Trend } from 'k6/metrics';
import { converse, newSession, pick, seedPairs } from './lib.js';

const pairs = new SharedArray('pares', () => seedPairs('../../data/seed/orders.jsonl'));

export const firstResponse = new Trend('first_response_ms', true);
export const noReply = new Counter('no_reply');
export const api5xx = new Counter('api_5xx');
export const replied = new Rate('replied');

export function conversationScenario(extra = {}) {
  return {
    executor: 'constant-arrival-rate',
    rate: Number(__ENV.RATE_PER_MIN || 12),
    timeUnit: '1m',
    duration: __ENV.DURATION || '5m',
    preAllocatedVUs: Number(__ENV.PRE_VUS || 20),
    maxVUs: Number(__ENV.MAX_VUS || 200),
    exec: 'conversation',
    ...extra,
  };
}

export const options = {
  scenarios: { conversa: conversationScenario() },
  thresholds: {
    first_response_ms: ['p(95)<4000'],
    no_reply: ['count==0'],
    api_5xx: ['count==0'],
  },
};

export function conversation() {
  const [customerId, orderId] = pick(pairs);
  const result = converse(newSession(customerId), `onde está meu pedido ${orderId}?`);
  const status = result.response ? result.response.status : 0;
  if (status >= 500) {
    api5xx.add(1);
  }
  check(status, { 'webhook aceito (200)': (s) => s === 200 });
  replied.add(result.reply !== null);
  if (result.reply === null) {
    noReply.add(1);
    return;
  }
  firstResponse.add(result.latencyMs, { source: result.reply.source });
}
