# 0009. Estratégia de avaliação como gate de CI

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Alterações em prompts e roteamento podem degradar o sistema sem quebrar testes unitários.

## Opções consideradas

1. Simulador de clientes (LLM persona) + LLM-as-judge calibrado + métricas determinísticas.
2. Apenas testes unitários com LLM fake.
3. Avaliação manual.

## Decisão

Opção 1. Golden set em `data/eval_scenarios/`, com um holdout que o CORE não vê. Métricas determinísticas (seleção e argumentos de ferramenta, ações irreversíveis sem confirmação, resolução, handoff, custo, latência) são o gate principal. O judge usa rubrica explícita e é calibrado contra ~30 conversas rotuladas, com concordância registrada (recalibrar se < 0,8). Subset rápido no PR; suíte completa em `main`. Ordem no histórico: baseline → ajuste de prompt → novo relatório.

## Consequências

- Positivas: regressões de comportamento detectadas; ganhos mensuráveis.
- Negativas: custo de chamadas de LLM no CI e não determinismo residual (mitigado com temperatura baixa e repetição).
