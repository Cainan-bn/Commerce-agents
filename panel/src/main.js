// Bootstrap do painel: token no sessionStorage, lista ao vivo, assumir/responder/encerrar.
import { createApi } from './api.js';
import { createStore } from './store.js';
import { renderHandoff } from './render.js';

const root = document.getElementById('app');
const store = createStore();
let api = null;
let agent = sessionStorage.getItem('panel_agent') || '';

function login() {
  root.replaceChildren();
  const form = document.createElement('form');
  const token = Object.assign(document.createElement('input'), {
    type: 'password',
    placeholder: 'Token do painel',
    required: true,
  });
  const name = Object.assign(document.createElement('input'), {
    placeholder: 'Seu nome',
    required: true,
    value: agent,
  });
  const submit = Object.assign(document.createElement('button'), {
    type: 'submit',
    textContent: 'Entrar',
  });
  form.append(token, name, submit);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    agent = name.value.trim();
    sessionStorage.setItem('panel_agent', agent);
    sessionStorage.setItem('panel_token', token.value);
    start();
  });
  root.append(form);
}

async function refresh() {
  store.setInitial(await api.listHandoffs());
  draw();
}

function draw() {
  root.replaceChildren(...store.list().map((handoff) => renderHandoff(handoff, document, actions)));
}

const actions = {
  async onClaim(handoff) {
    await api.claim(handoff.handoff_id, agent);
    await refresh();
  },
  async onReply(handoff) {
    const history = await api.messages(handoff.handoff_id);
    const text = window.prompt(
      `${history.map((m) => `${m.author}: ${m.text}`).join('\n')}\n\nSua resposta:`,
    );
    if (text) await api.reply(handoff.handoff_id, agent, text);
    await refresh();
  },
  async onClose(handoff) {
    await api.close(handoff.handoff_id);
    await refresh();
  },
};

async function start() {
  const token = sessionStorage.getItem('panel_token');
  if (!token) return login();
  api = createApi({
    baseUrl: window.location.origin,
    token,
    onUnauthorized: () => {
      sessionStorage.removeItem('panel_token');
      login();
    },
    onEvent: (event) => {
      // handoff_new do broker não traz o id: recarrega a lista para obtê-lo.
      if (event.type === 'handoff_new' || event.type === 'handoff_message') refresh().catch(() => {});
      else {
        store.apply(event);
        draw();
      }
    },
  });
  try {
    await refresh();
    api.connectPanel();
  } catch {
    login();
  }
}

start();
