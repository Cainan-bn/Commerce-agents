# 0002. Clean Architecture com import-linter como enforcement

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

Sistemas com LLMs tendem a misturar prompts, I/O e regras de negócio. Precisamos de fronteiras que sobrevivam a agentes autônomos escrevendo código.

## Direcionadores

- Domínio testável sem I/O nem framework.
- Troca de providers, banco e canais sem tocar regras.
- Enforcement automático, não por convenção.

## Opções consideradas

1. Clean Architecture em quatro camadas + import-linter.
2. Estrutura por feature sem camadas.
3. Camadas só por convenção.

## Decisão

Opção 1. Camadas: `domain` ← `application` ← `infrastructure` ← `interfaces`. Dependência só aponta para dentro. O CI roda import-linter com contratos `layers` e `forbidden` (por exemplo, `domain` não importa pydantic-ai, sqlalchemy, fastapi, langgraph). Violação quebra o build. Casos de uso dependem apenas de ports; adapters são injetados no composition root em `interfaces/`.

## Consequências

- Positivas: arquitetura verificada pelo CI; domínio puro.
- Negativas: mais arquivos e mapeamento entre DTOs e entidades.
- Nota: DTOs de fronteira usam Pydantic v2 em `application/dto`. O `domain` permanece sem dependências externas.
