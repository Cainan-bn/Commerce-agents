// Página do modo demonstração (ADR 0020): src/commerce_agents/interfaces/demo/index.html.
// HTML sem build e sem CDN, com script clássico (o jsdom não executa type="module").
// Contrato de DOM fixado:
// - #demo-notice visível com "modo demonstração";
// - #conversations lista GET /demo/conversations ({conversations: [...]}): um item
//   [data-conversation-id] por conversa, com o título e um botão [data-action="start"];
// - start faz POST /demo/session {customer_id} e abre o WebSocket em ws_path (+ token, se o
//   ws_path não o trouxer); mostra as mensagens da conversa como [data-suggested];
// - clicar numa sugestão faz POST /webhooks/web com X-Web-Session e {session_id, message_id, text};
// - a resposta do WebSocket entra em #transcript como TEXTO (nunca innerHTML).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const PAGE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../src/commerce_agents/interfaces/demo/index.html',
);

const CONVERSATIONS = {
  conversations: [
    {
      id: 'rastreio',
      title: 'Onde está meu pedido',
      customer_id: 'C0200',
      messages: ['Oi! Quero saber onde está o meu pedido que já foi enviado.'],
    },
    {
      id: 'cancelamento',
      title: 'Cancelar com confirmação',
      customer_id: 'C0167',
      messages: ['Quero cancelar o meu pedido.', 'Sim, pode cancelar.'],
    },
  ],
};
const SESSION = {
  token: 'tok.abc',
  conversation_id: 'web:demo-123',
  ws_path: '/ws/web/web%3Ademo-123',
};
const XSS = '<img src=x onerror="window.__xss = 1">';

function json(body, status = 200) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

async function flush(times = 10) {
  for (let i = 0; i < times; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function openPage() {
  const requests = [];
  const sockets = [];
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 1;
      sockets.push(this);
      setTimeout(() => this.onopen?.({}), 0);
    }
    send() {}
    close() {}
    addEventListener(type, handler) {
      this[`on${type}`] = handler;
    }
  }
  const dom = await JSDOM.fromFile(PAGE, {
    url: 'http://demo.test/demo',
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = async (url, init = {}) => {
        const target = new URL(url, 'http://demo.test/demo');
        requests.push({ path: target.pathname, init });
        if (target.pathname === '/demo/conversations') return json(CONVERSATIONS);
        if (target.pathname === '/demo/session') return json(SESSION);
        if (target.pathname === '/webhooks/web') return json({ accepted: 1 });
        return json({ detail: 'não encontrado' }, 404);
      };
      window.WebSocket = FakeWebSocket;
    },
  });
  await new Promise((resolve) => {
    if (dom.window.document.readyState === 'complete') resolve();
    else dom.window.addEventListener('load', resolve);
  });
  await flush();
  return { dom, document: dom.window.document, window: dom.window, requests, sockets };
}

async function start(page, id = 'cancelamento') {
  const item = page.document.querySelector(`[data-conversation-id="${id}"]`);
  item.querySelector('[data-action="start"]').click();
  await flush();
}

test('não usa CDN nem módulo ES (página sem build)', async () => {
  const { readFile } = await import('node:fs/promises');
  const html = await readFile(PAGE, 'utf-8');

  assert.doesNotMatch(html, /<script[^>]+src=["']https?:/i);
  assert.doesNotMatch(html, /<link[^>]+href=["']https?:/i);
  assert.doesNotMatch(html, /type=["']module["']/i);
});

test('mostra o aviso visível de modo demonstração', async () => {
  const { document, window } = await openPage();
  const notice = document.querySelector('#demo-notice');

  assert.ok(notice, '#demo-notice ausente');
  assert.match(notice.textContent.toLowerCase(), /modo demonstração/);
  assert.equal(notice.hidden, false);
  assert.notEqual(window.getComputedStyle(notice).display, 'none');
});

test('lista as conversas de /demo/conversations', async () => {
  const { document, requests } = await openPage();

  assert.ok(requests.some((r) => r.path === '/demo/conversations'));
  const items = [...document.querySelectorAll('#conversations [data-conversation-id]')];
  assert.deepEqual(
    items.map((el) => el.dataset.conversationId),
    ['rastreio', 'cancelamento'],
  );
  assert.match(items[1].textContent, /Cancelar com confirmação/);
});

test('iniciar cria a sessão do cliente e abre o WebSocket da conversa', async () => {
  const page = await openPage();
  await start(page);

  const session = page.requests.find((r) => r.path === '/demo/session');
  assert.ok(session, 'POST /demo/session não foi feito');
  assert.equal((session.init.method || '').toUpperCase(), 'POST');
  assert.deepEqual(JSON.parse(session.init.body), { customer_id: 'C0167' });
  assert.equal(page.sockets.length, 1);
  const url = new URL(page.sockets[0].url);
  assert.equal(url.protocol, 'ws:');
  assert.equal(url.host, 'demo.test');
  assert.equal(url.pathname, '/ws/web/web%3Ademo-123');
  assert.equal(url.searchParams.get('token'), SESSION.token);
});

test('mensagens sugeridas são clicáveis e enviam pelo webhook web com a sessão', async () => {
  const page = await openPage();
  await start(page);

  const suggested = [...page.document.querySelectorAll('[data-suggested]')];
  assert.deepEqual(
    suggested.map((el) => el.textContent.trim()),
    ['Quero cancelar o meu pedido.', 'Sim, pode cancelar.'],
  );
  suggested[0].click();
  await flush();

  const sent = page.requests.find((r) => r.path === '/webhooks/web');
  assert.ok(sent, 'POST /webhooks/web não foi feito');
  const headers = new Headers(sent.init.headers);
  assert.equal(headers.get('X-Web-Session'), SESSION.token);
  const body = JSON.parse(sent.init.body);
  assert.equal(body.session_id, 'demo-123');
  assert.equal(body.text, 'Quero cancelar o meu pedido.');
  assert.ok(body.message_id);
});

test('resposta do servidor é renderizada como texto, nunca como HTML', async () => {
  const page = await openPage();
  await start(page);
  page.sockets[0].onmessage?.({
    data: JSON.stringify({ type: 'message', message_id: 'reply:m1', text: XSS, source: 'agent' }),
  });
  await flush();

  const transcript = page.document.querySelector('#transcript');
  assert.ok(transcript.textContent.includes(XSS));
  assert.equal(page.document.querySelector('#transcript img'), null);
  assert.equal(page.window.__xss, undefined);
});
