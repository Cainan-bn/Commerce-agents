// Store do painel: ordena por prioridade e idade; eventos do WS aplicados de forma idempotente.
const PRIORITY_RANK = { urgent: 0, high: 1, normal: 2, low: 3 };

export function createStore() {
  const handoffs = new Map();

  function key(handoff) {
    return handoff.handoff_id ?? `conv:${handoff.conversation_id}`;
  }

  function setInitial(list) {
    handoffs.clear();
    for (const handoff of list) handoffs.set(key(handoff), { ...handoff });
  }

  function apply(event) {
    if (event.type === 'handoff_new') {
      const handoff = event.handoff;
      if (!handoffs.has(key(handoff))) handoffs.set(key(handoff), { ...handoff });
    } else if (event.type === 'handoff_claimed') {
      const current = handoffs.get(event.handoff_id);
      if (current) {
        handoffs.set(event.handoff_id, {
          ...current,
          status: 'claimed',
          claimed_by: event.claimed_by,
        });
      }
    } else if (event.type === 'handoff_closed') {
      handoffs.delete(event.handoff_id);
    }
  }

  function list() {
    return [...handoffs.values()].sort(
      (a, b) =>
        (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9) ||
        Date.parse(a.created_at) - Date.parse(b.created_at),
    );
  }

  return { setInitial, apply, list };
}
