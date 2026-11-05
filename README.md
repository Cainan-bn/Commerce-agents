# CommerceAgents

Sistema multi-agente de atendimento e vendas omnichannel para a **TH Multimarcas**, um e-commerce de moda e calçados de pequeno/médio porte. Case de portfólio de freelance.

> Status: Fase 00 (planejamento). Veja `docs/orchestration/progress.md`.

## Problema

A loja perde vendas fora do horário comercial. O time humano gasta a maior parte do tempo com perguntas repetitivas: status de pedido, disponibilidade de tamanho/estoque, prazo de frete e política de troca.

## O que o sistema faz

- Atende clientes por WhatsApp, Instagram DM e widget web (canais simulados por adapters no MVP).
- Consulta **dados reais** de pedido, estoque e frete por ferramentas MCP. Nunca inventa.
- Recomenda produtos com busca híbrida sobre o catálogo.
- Abre solicitações de troca e devolução.
- **Escala para humano** com resumo e contexto completos quando necessário.

## Escopo do MVP

1. Gateway de canais com normalização de mensagens e idempotência.
2. Orquestrador LangGraph: Supervisor + especialistas `Pedidos`, `CatalogoVendas`, `Politicas` (RAG) e `PosVenda`.
3. Roteador de intenção atrás de uma interface (baseline: modelo leve; evolução: SLM fine-tuned).
4. Ferramentas como servidores MCP sobre uma loja mock com dados seed realistas.
5. RAG de políticas com busca híbrida (`tsvector` + `pgvector`) e fusão RRF.
6. Execução durável (checkpointing do LangGraph em PostgreSQL).
7. Confirmação explícita obrigatória para ações irreversíveis.
8. Handoff humano via WebSocket com resumo da conversa.
9. Suíte de avaliação: simulador de clientes, LLM-as-judge e métricas determinísticas.
10. Resiliência (circuit breaker, fallback multi-provider, cache semântico), observabilidade (OpenTelemetry + Langfuse) e teste de carga (k6).

## Não-objetivos

- Integração real com plataformas de pagamento.
- Fine-tuning em GPU própria. Fica documentado como evolução futura em ADR.
- Frontend elaborado. Existe apenas um painel mínimo de handoff.
- Integração real com WhatsApp/Instagram. Os canais são simulados.

## Como rodar (WSL2)

Pré-requisitos: Windows com WSL2 (Ubuntu), Docker Desktop com integração WSL ativada e `gh` autenticado. O repositório deve ficar no filesystem Linux (nunca em `/mnt/c`).

```bash
git config --global core.autocrlf input
bash scripts/bootstrap_wsl2.sh   # idempotente
make doctor                      # confere toolchain, docker, gh e portas
make setup && make up            # sobe postgres+pgvector, redis, redpanda, otel, jaeger, langfuse
make lint && make test
```

A stack completa (com Langfuse v3 e ClickHouse) é pesada. Sugestão de `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=8GB
processors=4
swap=4GB
```

## Arquitetura

Clean Architecture com dependência `interfaces → infrastructure → application → domain`, imposta por import-linter no CI. Detalhes em [`docs/architecture/`](docs/architecture/) e decisões em [`docs/adr/`](docs/adr/).

## Como contribuir / processo

O trabalho é feito por um esquadrão de três agentes (Líder, CORE, OPS) via Task Cards. Veja [`docs/orchestration/`](docs/orchestration/). Commits seguem Conventional Commits em português; PRs são mergeados com merge commit.
