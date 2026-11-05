# 0007. Roteamento de modelos em cascata com fallback multi-provider

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Custo e latência dependem do modelo usado. A maior parte das perguntas é simples, e providers de LLM falham.

## Opções consideradas

1. Cascata: modelo leve primeiro, escalonando para modelo de fronteira por critério explícito; fallback entre providers.
2. Um único modelo de fronteira.
3. Um único provider.

## Decisão

Opção 1, atrás do port `LLMProvider`. Escalona quando a saída estruturada falha na validação, a confiança é baixa ou a tarefa exige raciocínio longo. Circuit breaker e retry com backoff + jitter por provider; fallback para o provider secundário e, esgotado, handoff humano. Orçamento de tokens por conversa. Cache semântico (Redis) apenas para perguntas de política, com limiar de similaridade e invalidação por versão do corpus.

## Consequências

- Positivas: custo menor e atendimento resiliente.
- Negativas: mais caminhos para testar; exige métricas por modelo (ADR 0009).
