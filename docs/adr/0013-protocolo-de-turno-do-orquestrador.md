# 0013. Protocolo de turno do orquestrador: decisões críticas em código, LLM só propõe

- Status: Accepted
- Data: 2026-11-06
- Refina: ADR 0003, 0008, 0010, 0011

## Contexto e problema

O grafo (ADR 0003) usa um LLM para entender o cliente e escolher ferramentas. Identidade do cliente, posse do pedido, confirmação de ações irreversíveis, handoff e recusa de injeção não podem depender do que o LLM "entendeu".

## Opções consideradas

1. Function calling nativo do provider, com o LLM decidindo tudo, inclusive a confirmação.
2. Protocolo próprio sobre `LLMProvider.complete`: o LLM devolve JSON (`ToolCall` | `FinalAnswer`) validado por schema; o código decide tudo que é crítico.
3. Loop manual sem LangGraph.

## Decisão

Opção 2, em LangGraph. O port `LLMProvider` não muda (texto), o que torna os testes com LLM roteirizado triviais e o provider trocável (ADR 0007).

- **Identidade e posse:** `customer_id` vem do canal e fica no estado; um `ScopedToolInvoker` envolve o `ToolInvoker`: força `customer_id` em `list_customer_orders`, e antes de `get_order_status`, `check_return_eligibility`, `cancel_order` e `open_return` confere (via leitura) que o pedido pertence ao cliente; senão devolve `not_found`, sem vazar existência.
- **Irreversíveis:** quando o LLM pede `cancel_order`/`open_return`, o grafo NÃO executa: chama `ProposeIrreversibleAction`, guarda a `PendingAction` no estado (checkpoint) e encerra o turno com o `summary`. No turno seguinte, se há `pending_action`, o nó `confirm` roda ANTES do supervisor: `classify_reply` + `ConfirmIrreversibleAction`. Resposta ao cliente nos desfechos EXECUTED/FAILED/DECLINED/UNCLEAR/EXPIRED vem de templates em código, nunca do LLM.
- **Prompt injection (ADR 0010):** texto do cliente, saídas de ferramentas e trechos de política entram no prompt dentro de delimitadores `<dados ...>` com instrução de sistema de que são dados; `detect_injection` marca `injection_flagged` (métrica/log, não bloqueia sozinho); a defesa real é estrutural (allowlist no executor, posse, confirmação em código); a resposta final passa por `sanitize_reply` (remove marcadores de prompt/sistema).
- **Falhas e limites:** JSON inválido do LLM → 1 reparo → `handoff`. Máximo de 4 passos de ferramenta por turno; orçamento de tokens por conversa; `ToolError` não retryable vira texto seguro ao LLM e o LLM pode explicar; `LLMProvider` indisponível → resposta fixa + handoff. Intenção com confiança < 0,5 ou `ambiguous` → pergunta de esclarecimento por template; `injection_guard` → recusa por template.
- **Citações:** resposta de `politicas` exige `citations` não vazio e todos presentes entre os `chunk_id` recuperados no turno; senão o grafo descarta a resposta e usa "não encontrei essa informação" + handoff.
- **Handoff:** nó `humano` publica `HandoffRequested` (Fase 07 ligará ao painel) e responde por template.

## Consequências

- Positivas: segurança independente do LLM, testável sem LLM real, métricas por nó.
- Negativas: protocolo JSON próprio (mais prompt e validação) em vez de function calling nativo; revisitar se o provider oferecer saída estruturada confiável.
