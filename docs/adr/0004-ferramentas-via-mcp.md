# 0004. Ferramentas expostas via MCP; agentes nunca acessam a loja diretamente

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Agentes precisam consultar pedidos, estoque e frete. Acesso direto ao banco ou à API da loja acopla o agente ao backend e amplia a superfície de ataque.

## Opções consideradas

1. Servidores MCP (`orders`, `catalog`, `shipping`, `returns`) sobre a loja mock.
2. Funções Python chamadas direto pelo agente.
3. SDK da loja injetado no agente.

## Decisão

Opção 1. Cada ferramenta tem schema Pydantic de entrada/saída, erros tipados e marcação `irreversible: bool`. Ferramentas irreversíveis exigem `confirmation_token` e `idempotency_key`. A loja real pode substituir a mock sem alterar agentes.

## Consequências

- Positivas: fronteira clara, testes de contrato, allowlist por agente (ADR 0010).
- Negativas: latência extra de um salto de protocolo e mais processos para operar.
