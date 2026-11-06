// Cliente da API do painel: Bearer, tratamento de 401 e reconexão do WS com backoff.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApi } from '../src/api.js';

test('requisições enviam Authorization: Bearer <token>', async () => {
  const seen = [];
  const fetchFn = async (url, init) => {
    seen.push({ url, headers: init.headers });
    return new Response(JSON.stringify([]), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  const api = createApi({ baseUrl: 'http://test', token: 'painel-teste', fetch: fetchFn });

  await api.listHandoffs();

  assert.equal(seen[0].headers.Authorization, 'Bearer painel-teste');
  assert.match(seen[0].url, /\/api\/handoffs$/);
});

test('resposta 401 dispara o callback de sessão inválida', async () => {
  let unauthorized = 0;
  const fetchFn = async () => new Response('', { status: 401 });
  const api = createApi({
    baseUrl: 'http://test',
    token: 'errado',
    fetch: fetchFn,
    onUnauthorized: () => {
      unauthorized += 1;
    },
  });

  await assert.rejects(api.listHandoffs());
  assert.equal(unauthorized, 1);
});

test('WS reconecta com backoff exponencial após fechar', async () => {
  const delays = [];
  const sockets = [];
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      sockets.push(this);
    }
    close() {}
  }
  const api = createApi({
    baseUrl: 'http://test',
    token: 'painel-teste',
    WebSocket: FakeWebSocket,
    sleep: async (ms) => {
      delays.push(ms);
    },
    onEvent: () => {},
  });

  api.connectPanel();
  for (let i = 0; i < 3; i += 1) {
    sockets[sockets.length - 1].onclose?.({ code: 1006 });
    await new Promise((resolve) => setImmediate(resolve));
  }

  assert.equal(sockets.length, 4);
  assert.ok(delays.length >= 3);
  assert.ok(delays[1] > delays[0]);
  assert.ok(delays[2] > delays[1]);
  assert.match(sockets[0].url, /\/ws\/panel\?token=painel-teste$/);
});
