# Progresso

## Fase 00 — Planejamento
- Estado: concluída na branch `fase/00-planejamento`, aguardando merge do PR.
- Entregas: README, ADRs 0001–0010, C4, metas de qualidade, contratos (ports, eventos, `AgentState`), backlog.
- Métricas: n/a (documentação e contratos).
- Riscos abertos: contratos ainda não verificados por `mypy --strict` e import-linter (entram na TASK-01-02); CORE e OPS dependem de terminais conectados no Maestri.
- Próxima fase: 01 — setup do ambiente (OPS).

## Fase 01 — Setup do ambiente
- Estado: concluída; stack validada com Docker (9 de 9 serviços healthy a partir de volumes zerados, health do Langfuse em 200) e CI verde no PR #2.
- Métricas: `make lint` verde (3 contratos import-linter); `make test` 14 passed, 100% branch.
- Riscos abertos: `REDIS_SOCKET_TIMEOUT_MS=0` no Langfuse é workaround de dev (reavaliar na Fase 10); pin exato do Langfuse 3.227.0 exige bump manual; Langfuse v3 é pesado para WSL2 (`.wslconfig` documentado no README).
- Próxima fase: 02 — dados e seed (CORE e OPS).
