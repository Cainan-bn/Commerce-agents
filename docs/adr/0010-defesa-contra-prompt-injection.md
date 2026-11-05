# 0010. Defesa contra prompt injection

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Mensagens de clientes e respostas de ferramentas são texto não confiável que pode tentar redefinir instruções ou acionar ferramentas indevidas.

## Opções consideradas

1. Defesa em profundidade: separação instrução/dado, allowlist por agente, validação de argumentos, decisões críticas em código.
2. Apenas instruções no system prompt.
3. Filtro de palavras-chave.

## Decisão

Opção 1.
- Conteúdo do cliente e das ferramentas entra sempre em blocos de dados delimitados, nunca concatenado ao bloco de instruções.
- Cada especialista tem allowlist de ferramentas aplicada no executor, fora do LLM.
- Todo argumento de ferramenta é validado por Pydantic (`strict`, `extra="forbid"`).
- Ações irreversíveis seguem o ADR 0008.
- A saída ao cliente nunca expõe prompts internos; cenários adversariais fazem parte do golden set (meta: 100% sem vazamento nem chamada fora da allowlist).

## Consequências

- Positivas: mitigação não dependente de um único mecanismo.
- Negativas: risco residual de injeção semântica; monitorado pelos evals.
