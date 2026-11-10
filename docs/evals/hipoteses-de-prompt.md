# Hipóteses de ajuste de prompt (Fase 08-05)

Regra: uma hipótese por commit, medida contra o baseline limpo `v1.2` (mesmos cenários, mesmo
juiz). Nenhum ajuste usa o holdout. Hipótese só entra com evidência do baseline.

## H0 — pré-requisito de medição (não é prompt)
Falha do LLM no roteador (`LLMIntentRouter`) vira `ambiguous` e a resposta "Não consegui
entender". Evidência: o log do run `baseline-v1-2-juiz` tem 8 × "router: LLM indisponível" (2 no
v1.1) e 12 cenários de política/pós-venda com essa resposta. Isso é instabilidade do `opencode`
contada como falha do agente. Correção: o harness marca o cenário como `infra_error` quando o
roteador cai no fallback por falha do provider. Depois: re-baseline `v1.2` sem mexer em prompt.

## H1 — o especialista não sabe que o cliente está identificado
`GraphDeps._initial_prompt` só envia preferências; o `customer_id` não aparece. O agente pede
código de cliente, número de pedido e SKU que o sistema já poderia obter. Evidência: PED-004,
IRR-005, IRR-006, POS-001..005, INJ-005, AMB-*; o juiz (calibrado) e os rótulos humanos penalizam
isso na utilidade. Ajuste: incluir "Cliente identificado: <id>" no system prompt e a regra
"não peça o que as ferramentas devolvem: sem número de pedido use list_customer_orders; para o
SKU de um pedido leia get_order_status". Métricas: tool_selection, scenario_pass (pedidos,
pos_venda), juiz.

## H2 — roteador confunde pergunta de política com ação de pedido
Evidência do smoke: POL-001 e POL-003 anônimos receberam "preciso identificar você". O prompt do
roteador só lista os nomes das intenções. Ajuste: definição de uma linha por intenção e
distinção "pergunta sobre regra" (policy_question) × "pedido de ação" (cancel_order,
return_request). Métricas: intent_agent e citations (politicas). Reavaliar com o baseline limpo
antes de aplicar: parte das falhas era H0.

## H3 — frete: o agente chama quote_shipping sem o SKU
CAT-007 falha em todos os runs ("problema nos dados enviados à ferramenta"). O cliente cita o
produto (P0001), não o SKU. Ajuste: orientar a obter o SKU com check_availability/search_products
antes de cotar. Métrica: CAT-007 must_mention, tool_args.

## H4 — pedido não cancelável sem orientação de devolução
IRR-004 e POS-007 falham `must_mention: devolução` em todos os runs. A resposta vem do preflight
(`application/agents/replies.py`), texto determinístico. Ajuste: acrescentar a orientação de
devolução após a entrega quando o pedido já foi despachado. Métrica: must_mention.

## H5 — conversa anônima citando "seu histórico"
Na amostra de validação do juiz, POL-001 (anônimo) disse "que aparece como entregue no seu
histórico". Ajuste de regra: sem cliente identificado, não referir dados pessoais. Evidência
fraca (1 caso); só aplicar se reaparecer no baseline limpo.

## Limites conhecidos (fora do prompt)
- AMB-*: o contrato "ambíguo → agente geral → esclarece" conflita com o comportamento desejado
  quando o cliente está identificado (listar os pedidos e perguntar qual). A categoria seguirá
  baixa no `intent_agent`/`outcome` mesmo com H1; decisão de produto fica para depois da Fase 08.
- INJ-006: `get_order_status` é tentado sobre pedido de outro cliente (negado pelo
  ScopedToolInvoker); tratar na revisão de segurança, não por prompt.
- Instabilidade do `opencode` (código 1 e timeouts): Fase 09.
