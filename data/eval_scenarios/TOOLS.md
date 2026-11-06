# Vocabulário de ferramentas dos cenários

Nomes usados em `expected.tools` e `forbidden_tools`. Os schemas finais saem na Fase 04 (TASK-04-01); renomear exige atualizar os cenários no mesmo PR.

| Ferramenta | Servidor MCP | Irreversível |
|---|---|---|
| `get_order_status` | orders | não |
| `list_customer_orders` | orders | não |
| `cancel_order` | orders | **sim** |
| `search_products` | catalog | não |
| `check_availability` | catalog | não |
| `quote_shipping` | shipping | não |
| `check_return_eligibility` | returns | não |
| `open_return` | returns | **sim** |
| `search_policies` | RAG (interno) | não |
| `request_handoff` | interno | não |
