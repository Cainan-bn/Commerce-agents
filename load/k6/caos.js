// Cenário caos: a carga de conversa.js com o LLM fora do ar no meio do run. O cenário `queda`
// liga LLM_STUB_DOWN aos CHAOS_AT e desliga após CHAOS_FOR. Espera: circuito abre, handoffs
// crescem, toda mensagem recebe resposta (do agente ou aviso de handoff) e a API não dá 5xx.
// Cada iteração é uma conversa nova: com handoff ativo, só a primeira mensagem tem aviso.
import http from 'k6/http';
import { sleep } from 'k6';
import { conversation, conversationScenario } from './conversa.js';

export { conversation };

const STUB_URL = __ENV.STUB_URL || 'http://localhost:8090';

export const options = {
  scenarios: {
    conversa: conversationScenario(),
    queda: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: 1,
      startTime: __ENV.CHAOS_AT || '90s',
      maxDuration: '30m',
      exec: 'outage',
    },
  },
  thresholds: {
    no_reply: ['count==0'],
    api_5xx: ['count==0'],
  },
};

function setDown(down) {
  const response = http.post(`${STUB_URL}/admin/mode`, JSON.stringify({ down }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'stub_admin' },
  });
  console.log(`stub down=${down} status=${response.status} em ${new Date().toISOString()}`);
}

export function outage() {
  setDown(true);
  sleep(Number(__ENV.CHAOS_FOR_S || 120));
  setDown(false);
}
