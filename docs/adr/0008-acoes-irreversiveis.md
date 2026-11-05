# 0008. Política de ações irreversíveis: confirmação explícita + idempotency key

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Cancelar pedido e abrir estorno não podem ser desfeitos e não podem depender de o LLM "ter entendido" o cliente.

## Opções consideradas

1. Token de confirmação de uso único + idempotency key, validados em código.
2. Instruir o LLM a pedir confirmação no prompt.
3. Aprovação humana sempre.

## Decisão

Opção 1. O agente propõe a ação; o sistema gera um `confirmation_token` (uso único, com expiração, vinculado a `conversation_id`, ação e argumentos) e apresenta ao cliente um resumo. Somente a resposta afirmativa do cliente, verificada pelo caso de uso `ConfirmIrreversibleAction`, consome o token e dispara a ferramenta com `idempotency_key`. Sem token válido, a ferramenta recusa. Evento `IrreversibleActionConfirmed` é auditado. Métrica bloqueante: zero ações sem confirmação.

## Consequências

- Positivas: segurança independente do LLM; retries seguros.
- Negativas: um turno adicional de conversa nas ações sensíveis.
