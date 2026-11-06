## Objetivo
RAG híbrido de políticas: chunking determinístico, ingestão idempotente, recuperação lexical (`tsvector` português, sem acento) + densa (`pgvector` HNSW) fundidas por RRF, com citação da fonte em cada trecho.

## Task Cards cobertos
- Líder: ADR 0012, contrato `docs/architecture/rag.md`, port `Embedder`, DTOs de ingestão
- TASK-05-01 / 01b / 01c testes red: chunking, RRF, ingestão, recuperação, qualidade e consultas fora de domínio (OPS)
- TASK-05-02 / 05-03 chunking e fusão puros, migration 0004, ingestão, `FastEmbedEmbedder`, `HybridPolicyRetriever`, `NullReranker`, calibração do limiar (CORE)
- TASK-05-04 métrica de recall usa a pergunta do cliente como consulta (OPS)

## ADRs criados
- 0012 Embeddings locais atrás de um port (modelo: `paraphrase-multilingual-MiniLM-L12-v2`, 384 dims; o `fastembed` não suporta e5-small).

## Como verificar
```bash
make lint && make test
make up && make migrate && make ingest-policies && make ingest-policies   # 2ª rodada: embeddings_computed = 0
make eval-rag                                                             # baixa ~220 MB do HF na 1ª vez
```

## Métricas
- 565 testes, cobertura 99%; mypy --strict e 4 contratos import-linter verdes.
- Ingestão: 59 chunks; 2ª execução 59 inalterados e 0 embeddings.
- `make eval-rag` (modelo real, n=8 cenários POL dev): recall@4 = 1,000 e MRR = 0,812 com a pergunta do cliente como consulta (metrica definida antes de medir); com a consulta de 1 palavra de `args.query`: recall@4 = 0,750, MRR = 0,688.
- Calibração do limiar denso (cosseno máx., modelo real): POL 0,31–0,66; perguntas naturais 0,62–0,73; fora de domínio exigidas 0,09–0,34; default `min_dense_similarity` = 0,45.

## Defeitos achados na revisão
1. Contrato e teste divergiam sobre a introdução antes da 1ª seção (corrigido, 05-01b).
2. `fail_after` do teste de falha da reingestão nunca disparava (05-01c).
3. `fastembed` não suporta o modelo do ADR: troca de modelo, mesma dimensão, sem nova migration.
4. Limiar de 0,30 do contrato não filtrava nada com o modelo real: calibrado a partir de medições.

## Riscos / pendências
- n=8 cenários é pouco para recall: o número é indicativo, não prova; ampliar o corpus de avaliação na Fase 08.
- Limiar denso global deixa vazar consultas próximas ao domínio ("cotação do dólar", 0,51). Mitigação prevista: o agente de Políticas só afirma o que o trecho cita e faz handoff sem fonte; rever com o reranker se a Fase 08 mostrar problema.
- Primeiro uso baixa ~220 MB; o eval real leva ~100 s e fica fora do CI padrão (marcador `embeddings`).
- `fastembed` aumenta a imagem Docker (onnxruntime).
