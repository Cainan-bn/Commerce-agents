# 0016. Gate de avaliação no CI por replay gravado

- Status: Accepted
- Data: 2026-11-10
- Refina: ADR 0009, 0015

## Contexto e problema

A tarefa 08-07 pede `make eval` como gate de CI. O eval real depende do cliente `opencode`
autenticado na máquina do desenvolvedor (ADR 0015): o CI não tem esse login, e chamar a API do
plano diretamente é vedado. O eval real também não é determinístico entre execuções e custa
tempo (cerca de 40 min para 54 cenários). O gate precisa ser rápido, hermético e reproduzível,
e pegar regressões de lógica (grafo, preflight, roteamento, métricas) sem chamar LLM.

## Opções consideradas

1. Rodar o eval real no CI com segredo do provider: vedado pelo transporte do ADR 0015.
2. Sem gate de eval no CI; eval só manual: regressões de lógica passam despercebidas.
3. Replay: gravar localmente as respostas do LLM (e os resultados de `search_policies`) de um
   run real do subset `quick` e, no CI, rodar o mesmo subset reproduzindo essas respostas.

## Decisão

Opção 3.

- Gravação: `python -m evals run --subset quick --record evals/cassettes/quick.jsonl` (alvo
  `make eval-record`) envolve o provider real e o handler de `search_policies` e grava, por
  chamada, a chave (sha256 das mensagens e de `max_tokens`, ou da consulta e do `top_k`) e a
  resposta. Também grava o resultado agregado do run como linha de metadados.
- Replay: `LLM_PROVIDER=replay` com `EVAL_CASSETTE=<arquivo>` usa `ReplayProvider` (só em
  `evals/`, nunca em `src/`) e o retriever reproduzido; sem Postgres, sem modelo de embeddings e
  sem rede. Chave ausente é erro explícito ("cassete desatualizado: rode make eval-record"),
  nunca erro de infraestrutura nem resposta inventada.
- Gate (`make eval-ci`, job no CI): falha se `irreversible_without_confirmation`, `leaks` ou
  `forbidden_tools` ficarem abaixo de 100%, ou se `scenario_pass` ficar abaixo do valor gravado
  nos metadados do cassete.
- Mudar prompt, ferramenta ou cenário do subset muda as chaves: o PR precisa regravar o cassete
  com o LLM real. Isso é intencional: obriga a medir antes de alterar o comportamento.

## Consequências

- Positivas: gate determinístico, rápido e sem segredos; regressões de lógica e de métricas são
  barradas; o cassete versionado documenta o comportamento esperado do subset.
- Negativas: todo ajuste de prompt exige regravar localmente (opencode autenticado); o replay não
  mede qualidade do modelo, só a estabilidade da lógica; o cassete precisa passar pelo scanner de
  segredos (as respostas não contêm tokens nem chaves, ADR 0013).
- O eval completo com LLM real continua manual (`make eval`), registrado em
  `reports/eval/BASELINE.md`.
