# RAG de políticas — contrato (Fase 05)

ADR 0005 (híbrido + RRF), ADR 0012 (embeddings). Corpus: `data/policies/*.md` (front matter `version`/`title`, seções `##`).

## Chunking (`application/rag/chunking.py`, puro, stdlib)
- `chunk_document(document: str, text: str) -> list[Chunk]`: lê o front matter (`title` obrigatório, senão `ValueError`), divide por seções `##`; o `# título` inicial não vira chunk, mas o texto entre ele e a primeira `##` (introdução), se houver, vira o primeiro chunk com `section = "Introdução"`. Seção com mais de 900 caracteres é dividida por parágrafos (linha em branco), juntando parágrafos até 900; um parágrafo maior que 900 vira um chunk sozinho. Sem sobreposição. Ordem e texto preservados; nada de timestamp ou aleatoriedade.
- `chunk_id = f"{document}#{position}"`; `content_hash` = sha256 de `title\nsection\ntext`.
- Texto indexado/embutido = `f"{title} > {section}\n{text}"` (contexto sem alterar `text`).
- `corpus_version(chunks) -> str`: sha256 hex (12 primeiros) dos `content_hash` ordenados por `chunk_id`.

## RRF (`application/rag/fusion.py`, puro)
`rrf_fuse(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]`: score = Σ 1/(k + rank) (rank 1-based); ordenado por score desc, empate por id asc; ids repetidos numa lista contam só a melhor posição; vazio → [].

## Persistência (migration 0004)
`policy_chunks(chunk_id PK, document, title, section, position, text, content_hash, model_name, corpus_version, embedding vector(384), search_vector tsvector GENERATED portuguese sobre unaccent(title||section||text), updated_at)`; GIN em `search_vector`, HNSW (`vector_cosine_ops`) em `embedding`. Extensão `vector` (e `unaccent`, já usada) garantidas na migration.

## Ingestão (`infrastructure/rag/ingestion.py`)
`PolicyIngestor(session_factory, embedder)` → `async ingest(policies_dir: Path) -> IngestionReport`. Idempotente: compara `content_hash` + `model_name`; só calcula embeddings dos chunks novos/alterados (ou todos se o modelo mudou); remove chunks que sumiram; tudo numa transação; `corpus_version` gravado em todos os chunks. Segunda execução: `embeddings_computed == 0`. Alvo `make ingest-policies`.

## Recuperação (`infrastructure/rag/retriever.py`)
`HybridPolicyRetriever(session_factory, embedder, *, candidates=20, rrf_k=60, min_dense_similarity=0.30, reranker=None)` implementa `PolicyRetriever.retrieve(query, k=4)`:
1. Lexical: `websearch_to_tsquery('portuguese', unaccent(query))`, top `candidates` por `ts_rank_cd`. Se a consulta lexical (AND) vier vazia, tenta OR dos termos (`plainto` com `|`), para não zerar consultas como "tênis preto".
2. Denso: top `candidates` por distância de cosseno; descarta similaridade < `min_dense_similarity`.
3. `rrf_fuse` → top `k` → `PolicyChunk(chunk_id, document, section, text, score=rrf, corpus_version)`.
4. Sem resultado lexical e sem denso acima do limiar → `[]` (o agente deve dizer que não sabe e/ou fazer handoff).
5. `reranker`: port opcional `Reranker.rerank(query, chunks) -> list[PolicyChunk]`, desligado por padrão (feature flag `RAG_RERANKER_ENABLED=false`); só `NullReranker` nesta fase (`infrastructure/rag/reranker.py`). Embedder real: `infrastructure/rag/embedder.py::FastEmbedEmbedder` (dependência `fastembed` em `dependencies`).
6. Consulta vazia ou > 300 caracteres → `ValueError`. Texto recuperado é dado, nunca instrução (ADR 0010): o retriever não interpreta o conteúdo.

## Qualidade (golden set)
Dev: 8 cenários `POL-*` (`search_policies` + `must_mention`). Métrica `recall@4` ≥ 0.9 e `MRR` medidos por `make eval-rag` com o modelo real (marcador `embeddings`); no CI padrão, `HashingEmbedder` valida só a mecânica.
