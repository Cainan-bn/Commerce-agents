// Render de um handoff como nó DOM. Todo texto entra por textContent: sem HTML injetado.
function element(document, tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function renderHandoff(handoff, document, actions = {}) {
  const root = element(document, 'article', undefined, `handoff priority-${handoff.priority}`);
  root.dataset.handoffId = handoff.handoff_id ?? '';
  root.append(
    element(document, 'h3', `${handoff.conversation_id} · ${handoff.priority}`),
    element(document, 'p', `Motivo: ${handoff.reason}`),
    element(document, 'p', handoff.summary, 'summary'),
    element(document, 'small', new Date(handoff.created_at).toLocaleString('pt-BR')),
  );
  if (handoff.claimed_by) {
    root.append(element(document, 'p', `Atendente: ${handoff.claimed_by}`));
  }

  const button = (label, handler) => {
    const node = element(document, 'button', label);
    node.type = 'button';
    node.addEventListener('click', () => handler?.(handoff));
    return node;
  };
  if (handoff.status === 'open') {
    root.append(button('Assumir', actions.onClaim));
  } else if (handoff.status === 'claimed') {
    root.append(button('Responder', actions.onReply), button('Encerrar', actions.onClose));
  }
  return root;
}

export function renderMessages(messages, document) {
  const list = element(document, 'ul', undefined, 'messages');
  for (const message of messages) {
    const item = element(document, 'li', message.text, `author-${message.author}`);
    list.append(item);
  }
  return list;
}
