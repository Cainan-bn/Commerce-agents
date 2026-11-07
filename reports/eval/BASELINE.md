# Baseline v1 (antes de qualquer ajuste de prompt)

Relatório: `20261107-154105-baseline-v1b.md` (o JSON bruto não é versionado: o detect-secrets tomaria o hash do corpus por segredo) (commit do código `f03904b`, 52 cenários dev,
agente `opencode-go/claude-haiku-5-5`, juiz `opencode-go/gpt-6-luna`, custo US$ 0,27).

- 50 cenários válidos; 2 com erro de infraestrutura do transporte (POL-004: opencode código 1;
  POS-001: timeout), fora das taxas.
- Gate `irreversible_without_confirmation`: 100%. `leaks`: 100%.
- `scenario_pass`: 42,3%.

## Defeitos conhecidos do harness/cenários (a corrigir ANTES de medir o tuning)

Nenhum prompt foi alterado. Estes itens são defeitos de medição, não do agente, e entram na
re-medição `baseline v1.1` (mesmos prompts):

- HND-001/002: `request_handoff` acontece no nó de handoff do grafo, não como chamada do LLM;
  a métrica de ferramenta não enxerga `handoff_events`.
- CAT-005, CAT-006, PED-006: `must_mention` literal demais ("indisponível", "preto",
  "não encontrado") frente a respostas corretas ("sem estoque", "preta", "não encontrei").
- IRR-002: cenário de um turno só, mas o `outcome: clarified` pressupõe resposta vaga do cliente.
- POS-007, IRR-004: o preflight do grafo consulta a loja direto (ADR 0013), então
  `get_order_status` não aparece como chamada de ferramenta.

Os demais itens com falha (roteador em perguntas de política anônimas, pedido de SKU/número do
pedido já conhecidos, AMB-*) são achados reais do agente, alvo da tarefa 08-05.
