// Cenário webhook (meta: p95 < 150 ms, gateway até a mensagem enfileirada no broker).
// Rampa até VUS usuários virtuais; cada um envia mensagens de clientes do seed com PACING_S de
// intervalo. Mede só o POST /webhooks/web: rode com o worker parado (load/run.sh faz isso).
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { newSession, pick, postMessage, seedPairs } from './lib.js';

const pairs = new SharedArray('pares', () => seedPairs('../../data/seed/orders.jsonl'));
const VUS = Number(__ENV.VUS || 50);

export const options = {
  scenarios: {
    webhook: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: __ENV.RAMP || '30s', target: VUS },
        { duration: __ENV.HOLD || '60s', target: VUS },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: {
    'http_req_duration{name:webhook}': ['p(95)<150'],
    'http_req_failed{name:webhook}': ['rate<0.01'],
  },
};

export default function () {
  const [customerId, orderId] = pick(pairs);
  const { response } = postMessage(newSession(customerId), `onde está meu pedido ${orderId}?`);
  check(response, { 'aceito (200)': (r) => r.status === 200 });
  sleep(Number(__ENV.PACING_S || 0.2));
}
