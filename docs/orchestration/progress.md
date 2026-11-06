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

## Fase 02 — Dados e seed
- Estado: concluída na branch `fase/02-dados-e-seed`; PR aberto, aguardando CI para merge.
- Métricas: 55 testes; 54 cenários dev + 12 holdout (privados, manifesto no repo); seed determinístico (300/200/1000).
- Riscos abertos: carga em PostgreSQL só na Fase 03; checkout compartilhado entre agentes (usar worktrees); Docker precisa estar ativo.
- Próxima fase: 03 — domínio e persistência (OPS escreve testes red, CORE implementa).

## Fase 03 — Domínio e persistência
- Estado: concluída na branch `fase/03-dominio-e-persistencia`; PR aberto, aguardando CI para merge.
- Métricas: 252 testes (38 de integração), cobertura 98%; seed carregado em Postgres (200/300/1000, 80 devoluções), idempotente.
- Riscos abertos: `save` sem lock otimista; busca textual com AND não casa cor; CORE e OPS agora em Claude Sonnet/Haiku.
- Próxima fase: 04 — ferramentas MCP (Líder especifica os schemas primeiro).

## Fase 04 — Ferramentas MCP
- Estado: concluída na branch `fase/04-ferramentas-mcp`; PR aberto, aguardando CI para merge.
- Métricas: 496 testes, cobertura 99%; ações irreversíveis só executam com token válido (uso único, Postgres) e idempotência; verificação de ponta a ponta entre processos feita pelo Líder.
- Riscos abertos: fallback em memória sem DB explícito; purga de tokens; heurística de confirmação a medir nos evals.
- Próxima fase: 05 — RAG de políticas (hybrid tsvector + pgvector + RRF).

## Fase 05 — RAG de políticas
- Estado: concluída na branch `fase/05-rag-politicas`; PR aberto, aguardando CI para merge.
- Métricas: 565 testes, cobertura 99%; recall@4 = 1,0 / MRR = 0,81 (n=8, modelo real, pergunta do cliente); ingestão idempotente (59 chunks, 2ª rodada sem embeddings).
- Riscos abertos: amostra pequena de avaliação; limiar denso global deixa vazar "cotação do dólar"; imagem maior por causa do onnxruntime.
- Próxima fase: 06 — orquestrador LangGraph (supervisor + 4 especialistas, checkpoint Postgres).

## Fase 06 — Orquestrador de agentes
- Estado: concluída na branch `fase/06-orquestrador-agentes`; PR aberto, aguardando CI para merge.
- Métricas: 687 testes, cobertura 99%; posse do pedido, pré-checagem, confirmação, citações e handoff decididos em código; checkpoint Postgres com retomada validada.
- Riscos abertos: sem provider real de LLM; handler de políticas ainda não ligado ao executor; UX de confirmação pendente.
- Próxima fase: 07 — canais (WhatsApp/Instagram/web) e handoff humano.
