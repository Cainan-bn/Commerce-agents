## Objetivo
Medir o agente com um harness de avaliação reproduzível (métricas determinísticas e juiz LLM calibrado), fixar um baseline limpo, ajustar prompts e contratos de ferramenta com evidência (uma hipótese por vez, TDD por par) e pôr um gate de avaliação no CI sem depender de LLM.

## Task Cards cobertos
- Líder: ADR 0015 (providers e cliente simulado por regra; adendo do transporte opencode), ADR 0016 (gate de CI por replay), `docs/evals/hipoteses-de-prompt.md`, `docs/evals/relatorio-fase-08.md`, rótulos de calibração do juiz, baselines e holdout.
- TASK-08-01* harness, métricas, trace, relatório, cliente simulado; correções de medição (OPS red / CORE green).
- TASK-08-03* juiz LLM (rubrica, contexto de ferramentas, calibração concorrente).
- TASK-08-05* erros de infraestrutura fora das taxas (upstream, queda do roteador), `--retry-infra`; hipóteses H1, H1b, H1c, H1d.
- TASK-08-09* concorrência/timeout configuráveis e tempo por fase; TASK-08-10* H4; TASK-08-11* H2; TASK-08-12* infraestrutura compartilhada (vazamento de memória); TASK-08-13* H3.
- TASK-08-07* replay gravado, `make eval-record`, `make eval-ci`, job `eval-gate`.
- TASK-08-08* schema dos cenários só aceita intenção, agente, ferramenta e argumentos do sistema.

## ADRs criados
- 0015 Providers de LLM (OpenAI-compatível e opencode CLI) e cliente simulado por regra.
- 0016 Gate de avaliação no CI por replay gravado.
- Adendo ao 0004: `get_order_status`/`list_customer_orders` expõem os itens do pedido (sku, qty).

## Como verificar
```bash
make lint && make test-unit
make eval-ci                       # replay do subset quick, sem LLM nem Postgres (~17 s)
# eval real (opencode autenticado, Postgres): make up && make ingest-policies && make seed-db
make eval LABEL=local              # ~40 min, 54 cenários
make eval-record                   # regrava o cassete após mudar prompt/ferramenta
```

## Métricas
- Dev (54 cenários, 0 erro de infraestrutura): `scenario_pass` 51,9% (baseline v1.2) → 70,4%; `tool_selection` 77,8% → 98,1%; `must_mention` 77,8% → 94,4%; `intent_agent` 70,4% → 77,8%. Gate de irreversíveis e `leaks` 100% em todos os runs.
- Holdout (12, rodado uma vez após o tuning): 16,7% bruto, 33,3% com vocabulário corrigido; gates de segurança 100%. Diagnóstico em `reports/eval/BASELINE.md`.
- Juiz LLM calibrado: 92,3% de concordância ±1 com rótulos humanos (100% na validação); sinal secundário, nunca gate.
- Eval completo: de horas (travou em 5h30) para ~40 min após a correção de memória do harness.
- 1004 testes unitários; mypy --strict e contratos import-linter verdes.

## Defeitos achados na revisão
1. Métricas: `forbidden_tools` contava chamadas não executadas; erros upstream e queda do LLM no roteador contavam como falha do agente (agora erro de infraestrutura).
2. `OrderView` descartava os itens do pedido: nenhum prompt resolveria a falta do SKU no pós-venda.
3. A regra da H1 convidava o agente a perguntar o item; o agente comparava prazos com uma data de "hoje" inventada.
4. Harness criava engine do Postgres e recarregava o modelo de embeddings por cenário (1,4 GB, swap): corrigido com `SharedInfra`.
5. Holdout com nomes de agente/intenção inexistentes passava pelo schema: agora o schema recusa.

## Riscos / pendências
- Lacunas do agente vistas no holdout e no dev: propor `open_return` quando o cliente pede devolução; insistência fora do prazo vai a humano; recusa vaga a quem se passa por outro cliente; INJ-006 chega a chamar a ferramenta (barrada pelo `ScopedToolInvoker`) — revisão de segurança.
- Contrato AMB (ambíguo → agente geral) conflita com o comportamento desejado para cliente identificado: decisão de produto.
- Transporte `opencode`: falhas pontuais; concorrência 8 piora. Circuit breaker e retries do provider na Fase 09.
- Sem provider real em produção (`UnconfiguredLLM`); decisão antes da Fase 10.
- Toda mudança de prompt exige regravar o cassete com o LLM real (intencional, ADR 0016).
