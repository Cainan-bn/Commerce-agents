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

## Baseline v1.1 (mesmos prompts, defeitos de medição corrigidos)

Relatório: `20261107-165513-baseline-v1-1.md` (código `54e9d11`, custo US$ 0,23). Substitui o v1 como
referência para o tuning. `scenario_pass` 52,9% (49 cenários válidos); gate de irreversíveis e
`leaks` em 100%. 3 cenários com erro de infraestrutura do transporte (POL-002 e POL-008:
opencode código 1; POS-001: timeout), fora das taxas. As falhas de infra variam entre runs
(no v1 foram POL-004 e POS-001): é instabilidade do `opencode`, tratada na Fase 09.

## Juiz LLM calibrado (08-03)

Juiz `opencode-go/gpt-6-luna`, rubrica de 4 critérios (nota geral = média arredondada). Rótulos
humanos em `data/judge_calibration/` (30 conversas + 10 de validação). Calibração 1 (juiz sem o
conteúdo das ferramentas nem a identificação do cliente): 76,7% de concordância ±1. Após dar
ao juiz o resultado das ferramentas e a identificação: 92,3% (26 pares) e 100% numa amostra
nova de 10 conversas (meta 0,8). Run de referência com juiz:
`20261108-004021-baseline-v1-2-juiz.md` (`scenario_pass` 51,9%, nota média 4,33, 36 julgados).
O juiz é sinal secundário; nunca é gate.

## Baseline limpo v1.2 (referência para o tuning 08-05)

Relatório: `20261108-baseline-v1-2.md` (código `ba1e67f`, sem alteração de prompt), 54 cenários
válidos e 0 erro de infraestrutura. `scenario_pass` 51,9%; gate de irreversíveis e `leaks` em 100%.
Consolidado de dois runs: `baseline-v1-4-juiz` (47 válidos) + reexecução avulsa dos 7 cenários que
ficaram sem resposta por indisponibilidade do `opencode` (POL-008, POS-001/002/003/004/006/007),
mesmo commit e mesmos prompts. As falhas desses 7 não trazem trecho da resposta (o relatório
avulso não guardou o trace). A nota do juiz não entra: nesse run só 11 cenários foram julgados
(o transporte caiu no juiz também); a referência de nota segue sendo `baseline-v1-2-juiz` (4,33).

## H1 — cliente identificado no prompt (`404bb42`)

Relatório: `20261108-h1-consolidado.md` (54 válidos, 0 infra; consolidado do run `h1-pedidos-posvenda`
com a reexecução avulsa de POL-008, POS-001/003/005, como no v1.2). `scenario_pass` 51,9% → 57,4%,
`tool_selection` 77,8% → 83,3%. Pedidos 78,6% → 85,7% (PED-004 passou). Gate e `leaks` 100%.
`pos_venda` não melhorou (12,5%): o agente agora acha o pedido, mas pergunta "qual item" em vez de
ler o SKU em `get_order_status` e chamar `check_return_eligibility` (POS-002/004, IRR-005). A
regra da H1 chega a convidar essa pergunta; ajuste na H1b. A alta em `politicas` (37,5% → 62,5%)
não tem relação com a H1 (o ajuste não toca esse agente): variação entre runs/infra.

## H1b + H1c — SKU do pedido (`74e490e`, `6f66a13`)

H1b (regra de devolução do `pos_venda`) sozinha não resolveu: `OrderView` descartava os itens que a
loja devolve, então nenhuma ferramenta entregava o SKU (IRR-005: "o sistema não me mostrou os
itens"). H1c expõe `items` (sku, qty) em `get_order_status`/`list_customer_orders` (ADR 0004).
Relatório: `20261109-013334-h1c-itens-pedido.md` (54 válidos, 0 infra, sem juiz).
`tool_selection` 77,8% (v1.2) → 88,9%; `pos_venda` tool_selection 25% → 87,5%, `scenario_pass`
12,5% → 25%. `scenario_pass` geral 57,4% (igual à H1): os ganhos de tool_selection ainda não
fecham o cenário porque as falhas restantes são `must_mention`/`intent_agent` e o relógio do
mock da loja (POS-001/002 respondem "elegível até 02/11" com hoje em 08/11). Gate e `leaks` 100%.

## H1d — confiar em `eligible` (`940e8bc`) e teste de concorrência 8

Relatório: `20261109-134527-h1d-eligible.md` (54 válidos, 0 infra após reexecução, sem juiz).
`scenario_pass` 57,4% → 59,3%; POS-002 passou (o agente deixou de comparar com "hoje").
`tool_selection` 88,9%; gate e `leaks` 100%. Restam em `pos_venda`: POS-001 (`must_mention`
"7 dias": a resposta cita a data, não o prazo), POS-003/004 (`intent_agent`), POS-005, POS-007.
Tempo: `--concurrency 8 --llm-timeout 90` foi pior que o esperado: 41 dos 54 cenários caíram em
infra na 1ª passada (opencode não aguenta 8 chamadas simultâneas) e o run levou 75 min
(agente 58, reexecução 17). Manter `--concurrency 4` como padrão até a Fase 09.

## H4 — orientação de devolução no preflight (`5b0884c`)

Relatório: `20261109-152317-h4-devolucao.md` (54 válidos, 0 infra após reexecução, `--concurrency 4`,
tempo 68 min: agente 61, reexecução 8). `scenario_pass` 59,3% → 61,1%, `tool_selection` 90,7%,
`must_mention` 85,2%. IRR-004 e POS-007 passaram. Gate e `leaks` 100%. `politicas` caiu a 37,5%
(era 62,5%): os 5 cenários que falham ali são anônimos e recebem "preciso identificar você"
(roteador, H2); o agente de políticas não foi tocado, então a oscilação vem do roteador, não da H4.
