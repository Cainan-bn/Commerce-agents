# 0011. Consumo do token de confirmação no servidor da ferramenta

- Status: Accepted
- Data: 2026-11-06
- Refina: ADR 0008

## Contexto e problema

O ADR 0008 diz que o caso de uso `ConfirmIrreversibleAction` consome o token e dispara a ferramenta. Se o consumo ficar só no orquestrador, uma ferramenta chamada por outro caminho (bug, injeção, novo agente) executaria sem confirmação. Além disso, um timeout depois do consumo impediria o retry seguro com o mesmo token.

## Opções consideradas

1. Consumir no `ConfirmIrreversibleAction` e chamar a ferramenta sem token.
2. Consumir no servidor MCP da ferramenta, que recusa sem token válido; `ConfirmIrreversibleAction` apenas valida a resposta afirmativa do cliente e repassa o token.
3. Consumir nos dois lados.

## Decisão

Opção 2. O servidor da ferramenta é o ponto de aplicação da regra, independente do LLM e do orquestrador:

- Ordem: (a) se `idempotency_key` já tem resultado com os mesmos argumentos, devolve o resultado guardado; (b) com argumentos diferentes, `idempotency_conflict`; (c) senão consome o token (`ConfirmationTokenStore.consume`, digest = sha256 de JSON canônico dos `action_fields`), recusa com `confirmation_required`/`confirmation_invalid` se falhar; (d) chama a loja com `Idempotency-Key`; (e) guarda o resultado sob a chave.
- A `idempotency_key` é gerada na proposta e guardada junto do token no estado da conversa; retries reutilizam a mesma chave.
- Falhas transitórias (`upstream_timeout`, `upstream_unavailable`) são as únicas repetidas automaticamente; ferramentas irreversíveis fazem no máximo 1 retry, sempre com a mesma chave.
- `ConfirmIrreversibleAction` verifica a resposta afirmativa do cliente contra a proposta pendente e emite `IrreversibleActionConfirmed`.

## Consequências

- Positivas: segurança por construção (zero ações sem token mesmo com o orquestrador comprometido); retry seguro; contrato testável sem LLM.
- Negativas: o servidor precisa de acesso ao `ConfirmationTokenStore` e a um registro de idempotência; o contrato de erros cresce.
