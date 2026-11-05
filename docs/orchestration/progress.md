# Progresso

## Fase 00 — Planejamento
- Estado: concluída na branch `fase/00-planejamento`, aguardando merge do PR.
- Entregas: README, ADRs 0001–0010, C4, metas de qualidade, contratos (ports, eventos, `AgentState`), backlog.
- Métricas: n/a (documentação e contratos).
- Riscos abertos: contratos ainda não verificados por `mypy --strict` e import-linter (entram na TASK-01-02); CORE e OPS dependem de terminais conectados no Maestri.
- Próxima fase: 01 — setup do ambiente (OPS).

## Fase 01 — Setup do ambiente
- Estado: implementada na branch `fase/01-setup-ambiente`, PR aberto; merge aguarda CI verde e validação de `make up` com Docker.
- Métricas: `make lint` verde (3 contratos import-linter); `make test` 14 passed, 100% branch.
- Riscos abertos: Docker indisponível no WSL2 do desenvolvedor (runtime do compose e do `docker build` não verificados); Langfuse v3 é pesado para WSL2 (sugerir `.wslconfig` com ≥ 8 GB no README).
- Próxima fase: 02 — dados e seed (CORE e OPS).
