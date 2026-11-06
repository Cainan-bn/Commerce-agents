// Render do painel: escapa o texto do cliente (sem XSS) e mostra ações conforme o status.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { renderHandoff } from '../src/render.js';

const { window } = new JSDOM('<!doctype html><body></body>');
const { document } = window;

const base = {
  handoff_id: 'h1',
  conversation_id: 'web:s1',
  priority: 'high',
  reason: 'cliente pediu humano',
  summary: 'Cliente quer trocar tamanho',
  created_at: '2026-11-06T10:00:00Z',
  claimed_by: null,
};

test('texto malicioso do cliente nunca vira elemento HTML', () => {
  const malicious = { ...base, summary: '<img src=x onerror="alert(1)">', status: 'open' };

  const node = renderHandoff(malicious, document);

  assert.equal(node.querySelector('img'), null);
  assert.ok(node.textContent.includes('<img src=x onerror="alert(1)">'));
});

test('resumo e motivo aparecem como texto', () => {
  const node = renderHandoff({ ...base, status: 'open' }, document);

  assert.ok(node.textContent.includes('Cliente quer trocar tamanho'));
  assert.ok(node.textContent.includes('cliente pediu humano'));
});

test('handoff open oferece assumir e não oferece responder nem encerrar', () => {
  const node = renderHandoff({ ...base, status: 'open' }, document);
  const labels = [...node.querySelectorAll('button')].map((b) => b.textContent.trim().toLowerCase());

  assert.ok(labels.some((l) => l.includes('assumir')));
  assert.ok(!labels.some((l) => l.includes('responder')));
  assert.ok(!labels.some((l) => l.includes('encerrar')));
});

test('handoff claimed oferece responder e encerrar, sem assumir', () => {
  const node = renderHandoff({ ...base, status: 'claimed', claimed_by: 'agente-ana' }, document);
  const labels = [...node.querySelectorAll('button')].map((b) => b.textContent.trim().toLowerCase());

  assert.ok(labels.some((l) => l.includes('responder')));
  assert.ok(labels.some((l) => l.includes('encerrar')));
  assert.ok(!labels.some((l) => l.includes('assumir')));
  assert.ok(node.textContent.includes('agente-ana'));
});

test('handoff closed não mostra botões de ação', () => {
  const node = renderHandoff({ ...base, status: 'closed' }, document);

  assert.equal(node.querySelectorAll('button').length, 0);
});
