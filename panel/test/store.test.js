// Store do painel: ordena handoffs por prioridade e idade; aplica eventos WS de forma idempotente.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../src/store.js';

const handoff = (id, priority, createdAt, status = 'open') => ({
  handoff_id: id,
  conversation_id: `web:${id}`,
  status,
  priority,
  summary: `resumo ${id}`,
  reason: 'motivo',
  created_at: createdAt,
  claimed_by: null,
});

test('lista ordena por prioridade (urgent > high > normal > low) e depois por idade', () => {
  const store = createStore();
  store.setInitial([
    handoff('a', 'normal', '2026-11-06T10:00:00Z'),
    handoff('b', 'urgent', '2026-11-06T11:00:00Z'),
    handoff('c', 'normal', '2026-11-06T09:00:00Z'),
    handoff('d', 'high', '2026-11-06T08:00:00Z'),
  ]);

  assert.deepEqual(store.list().map((h) => h.handoff_id), ['b', 'd', 'c', 'a']);
});

test('evento handoff_new adiciona o handoff uma vez', () => {
  const store = createStore();
  const event = { type: 'handoff_new', handoff: handoff('x', 'high', '2026-11-06T10:00:00Z') };

  store.apply(event);
  store.apply(event);

  assert.equal(store.list().length, 1);
});

test('evento handoff_claimed muda o status e o responsável', () => {
  const store = createStore();
  store.setInitial([handoff('h1', 'normal', '2026-11-06T10:00:00Z')]);

  store.apply({ type: 'handoff_claimed', handoff_id: 'h1', claimed_by: 'agente-ana' });

  const updated = store.list().find((h) => h.handoff_id === 'h1');
  assert.equal(updated.status, 'claimed');
  assert.equal(updated.claimed_by, 'agente-ana');
});

test('evento handoff_closed remove o handoff da lista ativa, idempotente', () => {
  const store = createStore();
  store.setInitial([handoff('h2', 'normal', '2026-11-06T10:00:00Z')]);

  store.apply({ type: 'handoff_closed', handoff_id: 'h2' });
  store.apply({ type: 'handoff_closed', handoff_id: 'h2' });

  assert.equal(store.list().length, 0);
});

test('aplicar a mesma sequência de eventos duas vezes produz o mesmo estado', () => {
  const events = [
    { type: 'handoff_new', handoff: handoff('z', 'low', '2026-11-06T10:00:00Z') },
    { type: 'handoff_claimed', handoff_id: 'z', claimed_by: 'agente-bruno' },
  ];
  const once = createStore();
  events.forEach((e) => once.apply(e));
  const twice = createStore();
  events.concat(events).forEach((e) => twice.apply(e));

  assert.deepEqual(twice.list(), once.list());
});
