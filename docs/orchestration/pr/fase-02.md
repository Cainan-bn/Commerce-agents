## Objetivo
Entregar os dados antes do schema: seed realista da TH Multimarcas, corpus de políticas, golden set de avaliação, mock_store com falhas injetáveis e `make seed` idempotente.

## Task Cards cobertos
- TASK-02-01 gerador determinístico (CORE): 300 produtos, 200 clientes, 1.000 pedidos
- TASK-02-02 / 02-02b corpus de políticas, 6 arquivos (CORE)
- TASK-02-03 / 02-03b golden set de dev, 54 cenários (CORE)
- TASK-02-04 / 02-04b mock_store FastAPI e idempotência escopada por recurso (OPS)
- TASK-02-05 `make seed` idempotente (OPS)
- TASK-02-06 entregas recentes no seed (CORE), achado da revisão do Líder
- Líder: contrato dos dados, vocabulário de ferramentas, holdout (12 cenários, fora do repo; manifesto de hashes versionado)

## ADRs criados
Nenhum (decisões cobertas pelo ADR 0009; o holdout fora do repositório é aplicação dele).

## Como verificar
```bash
make seed && git status --porcelain data/seed   # vazio
make lint && make test
make mock                                        # API fake em :8001
```

## Métricas
- `make test`: 55 testes; `make lint`: ruff, mypy --strict e 4 contratos import-linter verdes.
- Seed: distribuição de status exata vs. alvo; 0 violações de integridade; 15,0% das variações sem estoque; 46 entregas dentro da janela de troca; geração byte a byte determinística.
- Golden set: 54 cenários dev (pedidos 14, ambíguo 8, políticas 8, catálogo 7, pós-venda 8, injection 6, handoff 3) + 12 holdout privados.

## Defeitos achados na revisão do Líder
1. Idempotência do mock_store não era escopada por pedido (corrigido, 02-04b).
2. Seed tinha só 2 entregas na janela de troca (corrigido, 02-06; pedidos O000001–O000100 congelados).
3. Holdout compartilhava entidades com o dev (refeito; 0 sobreposições).
4. Política de cancelamento ausente (02-02b).

## Riscos / pendências
- `make seed` não carrega PostgreSQL ainda; as migrations (Fase 03) são derivadas destes dados.
- Os 3 agentes compartilharam um único checkout; nas próximas fases usar git worktrees.
- Docker Desktop precisa estar ativo para os testcontainers da Fase 03.
