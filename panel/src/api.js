// Cliente da API do painel: Bearer, tratamento de 401 e WebSocket com reconexão (backoff).
const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 15000;

export function createApi({
  baseUrl,
  token,
  fetch: fetchFn = globalThis.fetch,
  WebSocket: WebSocketImpl = globalThis.WebSocket,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  onUnauthorized = () => {},
  onEvent = () => {},
}) {
  async function request(path, { method = 'GET', body } = {}) {
    const headers = { Authorization: `Bearer ${token}` };
    const init = { method, headers };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const response = await fetchFn(`${baseUrl}${path}`, init);
    if (response.status === 401) {
      onUnauthorized();
      throw new Error('sessão inválida');
    }
    if (!response.ok) throw new Error(`erro ${response.status}`);
    return response.json();
  }

  function connectPanel() {
    const wsBase = baseUrl.replace(/^http/, 'ws');
    let attempt = 0;
    let closedByUser = false;
    let current = null;

    const open = () => {
      const socket = new WebSocketImpl(`${wsBase}/ws/panel?token=${encodeURIComponent(token)}`);
      current = socket;
      socket.onopen = () => {
        attempt = 0;
      };
      socket.onmessage = (message) => {
        try {
          onEvent(JSON.parse(message.data));
        } catch {
          // mensagem inválida do servidor é ignorada
        }
      };
      socket.onclose = async () => {
        if (closedByUser) return;
        const delay = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
        attempt += 1;
        await sleep(delay);
        if (!closedByUser) open();
      };
    };
    open();
    return {
      close() {
        closedByUser = true;
        current?.close();
      },
    };
  }

  const id = (handoffId) => encodeURIComponent(handoffId);
  return {
    connectPanel,
    listHandoffs: () => request('/api/handoffs'),
    messages: (handoffId) => request(`/api/handoffs/${id(handoffId)}/messages`),
    claim: (handoffId, agent) =>
      request(`/api/handoffs/${id(handoffId)}/claim`, { method: 'POST', body: { agent } }),
    reply: (handoffId, agent, text) =>
      request(`/api/handoffs/${id(handoffId)}/reply`, { method: 'POST', body: { agent, text } }),
    close: (handoffId) => request(`/api/handoffs/${id(handoffId)}/close`, { method: 'POST' }),
  };
}
