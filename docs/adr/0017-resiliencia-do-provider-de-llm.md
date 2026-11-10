# 0017. Resiliência do provider de LLM: circuit breaker, fallback e degradação para humano

- Status: Accepted
- Data: 2026-11-10
- Refina: ADR 0007, 0015

## Contexto e problema

Na Fase 08 o transporte do LLM falhou com frequência (código 1, timeouts, janelas de
indisponibilidade). Hoje cada provider faz retry com backoff e jitter, e o grafo, quando o
provider levanta `LLMUnavailableError`, responde com `llm_unavailable()` e encaminha a humano.
Falta: (1) parar de bater num provider que está caído (cada chamada espera o timeout inteiro e
os retries, o que multiplica a latência do atendimento e a carga no provider); (2) usar um
segundo provider quando o primeiro cai (ADR 0007 prevê fallback multi-provider); (3) medir
isso. A meta da fase é: queda do provider primário não derruba o atendimento (fallback ou
handoff) e a primeira resposta com LLM fica abaixo de 4 s no p95.

## Opções consideradas

1. Só retry por provider (estado atual).
2. Decoradores sobre o port `LLMProvider`: circuit breaker por provider e cadeia de fallback,
   compostos na composição da aplicação; o grafo não muda.
3. Biblioteca externa de resiliência (tenacity, pybreaker) dentro de cada adaptador.
4. Cache semântico de respostas para reduzir chamadas.

## Decisão

Opção 2, em `infrastructure/llm/`:

- `CircuitBreakerLLM(inner, *, name, failure_threshold, window_s, open_s, clock)`: estados
  fechado → aberto → meio-aberto. Abre após `failure_threshold` falhas de
  `LLMUnavailableError` dentro de `window_s`; aberto, falha na hora com
  `LLMUnavailableError("circuito aberto: <name>")` sem chamar o provider; após `open_s` deixa
  passar uma chamada de teste (meio-aberto): sucesso fecha, falha reabre. `LLMBadRequestError`
  (erro do pedido, não do provider) não conta como falha. Relógio injetável; sem sleeps.
- `FallbackLLM(providers)`: tenta em ordem; passa ao próximo só em `LLMUnavailableError`
  (inclusive circuito aberto); se todos falharem, levanta `LLMUnavailableError` com a lista de
  motivos. O resultado informa o provider que respondeu (para métricas e custo).
- Composição por ambiente: primário (`LLM_*`) e secundário opcional (`LLM_FALLBACK_PROVIDER`,
  `LLM_FALLBACK_MODEL`, `LLM_FALLBACK_BASE_URL`, `LLM_FALLBACK_API_KEY`), cada um envolvido no
  seu breaker. Sem secundário, o breaker sozinho já corta a espera e o grafo degrada para
  humano como hoje.
- O retry continua dentro de cada adaptador (já existe); o breaker fica por fora dele.
- O roteador usa o mesmo provider resiliente; a queda dele já cai em `ambiguous` com
  `on_failure` (Fase 08).
- Métricas (ADR 0009, card de observabilidade): estado do circuito, aberturas, chamadas por
  provider, uso do fallback.
- Cache semântico (opção 4): fora desta fase. As respostas dependem de dados do cliente e de
  ferramentas (pedido, estoque), e um acerto falso daria informação errada ou de outro cliente;
  só faria sentido para perguntas de política anônimas, que já são baratas.

## Consequências

- Positivas: provider caído para de consumir tempo de cada conversa; fallback configurável sem
  mudar o grafo; comportamento testável com relógio falso.
- Negativas: parâmetros do breaker precisam de calibração (começam conservadores:
  5 falhas em 60 s, aberto por 30 s); duas chaves de provider para operar o fallback; respostas
  do secundário podem diferir em qualidade (medir com o eval antes de pôr em produção).
