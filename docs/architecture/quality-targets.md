# Metas de qualidade

Metas numéricas de aceite. Relaxar uma meta exige ADR com a justificativa e a medição. Nunca silenciosamente.

## Código

| Critério | Meta | Verificação |
|---|---|---|
| Tipagem | `mypy --strict` sem erros; sem `Any` explícito em `domain/` e `application/` | `make lint` |
| Lint/format | `ruff check` e `ruff format --check` limpos | `make lint` |
| Arquitetura | contratos import-linter 100% respeitados | `make lint` |
| Cobertura (branch) | ≥ 90% `domain/`; ≥ 85% `application/`; ≥ 70% global | `make test` |
| Validação | Pydantic v2 `strict=True`, `extra="forbid"` em DTOs de fronteira | revisão + testes |
| SOLID | casos de uso dependem só de ports; adapters no composition root | import-linter + revisão |
| Erros | erros de domínio tipados; sem `except Exception` sem re-raise ou log estruturado | revisão |
| Assincronia | I/O 100% async no caminho de requisição | revisão + testes |
| Segurança | sem segredos; sem CVE crítica; webhooks com assinatura verificada | detect-secrets, Trivy, pip-audit |
| Documentação | ADR por decisão significativa; docstrings em ports e casos de uso | revisão |

## IA e avaliação (gate de CI a partir da Fase 08)

| Métrica | Meta |
|---|---|
| Ações irreversíveis sem confirmação | **0** (bloqueante) |
| Acurácia de seleção de ferramenta | ≥ 95% |
| Acurácia de argumentos de ferramenta | ≥ 95% |
| Resolução sem humano (cenários resolvíveis) | ≥ 80% |
| Fidelidade às fontes em políticas (judge) | ≥ 0,9 |
| Resistência a prompt injection | 100% |
| Concordância judge × humano | registrada; recalibrar se < 0,8 |

## Sistema (Fase 09)

| Métrica | Meta |
|---|---|
| Latência excluindo LLM (gateway → resposta enfileirada), p95 | < 150 ms |
| Primeira resposta ao cliente com LLM, p95 | < 4 s |
| Degradação graciosa | queda do provider primário não derruba o atendimento (fallback ou handoff) |
| Idempotência | mensagem duplicada nunca gera resposta ou ação duplicada |
| Observabilidade | 100% das conversas com trace correlacionado por `conversation_id` |
| Custo | custo médio por conversa resolvida medido e reportado no README |
