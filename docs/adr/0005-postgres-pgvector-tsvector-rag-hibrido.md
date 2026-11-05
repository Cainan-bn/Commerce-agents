# 0005. PostgreSQL + pgvector + tsvector para RAG híbrido

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

O RAG de políticas precisa de busca lexical (termos exatos como "30 dias", "CDC") e semântica. O corpus é pequeno (dezenas de documentos).

## Opções consideradas

1. PostgreSQL com `tsvector` (dicionário `portuguese`) + `pgvector` (HNSW), fusão RRF.
2. Vector DB dedicado (Qdrant, Weaviate) + Elasticsearch.
3. Apenas busca densa.

## Decisão

Opção 1. Já usamos PostgreSQL para estado, checkpoints e dados; uma só peça operacional reduz custo e permite transações e filtros por metadados. A fusão é por **Reciprocal Rank Fusion** (k=60). Reranking por cross-encoder fica atrás de feature flag; se entrar no caminho padrão, um ADR complementar avalia custo × latência. Respostas sempre citam o trecho-fonte.

## Consequências

- Positivas: simplicidade operacional, consistência transacional.
- Negativas: escala limitada comparada a engines dedicadas. Aceitável no MVP; revisitar acima de ~1M chunks.
