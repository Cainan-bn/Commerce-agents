# 0012. Embeddings locais (fastembed, multilingual-e5-small) atrás de um port

- Status: Accepted
- Data: 2026-11-06
- Complementa: ADR 0005, ADR 0007

## Contexto e problema

O RAG híbrido (ADR 0005) precisa de embeddings em português. O projeto roda em WSL2, com CI gratuito e sem garantia de chave de API; o corpus tem dezenas de trechos e a ingestão deve ser reproduzível.

## Opções consideradas

1. API hospedada (OpenAI/Cohere/Voyage): melhor qualidade bruta, mas exige chave, rede e custo em cada ingestão e em cada consulta; acopla CI a um terceiro.
2. Modelo local via `fastembed` (ONNX) com `intfloat/multilingual-e5-small` (384 dims, multilíngue): offline após o download, determinístico, sem custo; ~120 MB de modelo e cold start.
3. `sentence-transformers` (PyTorch): mesma ideia, dependência muito mais pesada.

## Decisão

Opção 2, atrás do port `Embedder` (`embed_documents`, `embed_query`, `dimension`, `model_name`). Detalhes:

- Prefixos do e5: `passage: ` na ingestão e `query: ` na consulta, aplicados dentro do adaptador.
- A coluna é `vector(384)` com índice HNSW (cosseno). Trocar de modelo exige nova migration e reingestão; `model_name` é gravado por chunk e a ingestão reindexa tudo quando o modelo mudar.
- Testes padrão usam um `HashingEmbedder` determinístico (bag-of-words por hash) que valida a mecânica (RRF, idempotência, SQL); a qualidade semântica é medida num alvo separado `make eval-rag` (recall@k com o modelo real, marcador `embeddings`), fora do CI padrão para não depender de download.
- Um adaptador de API hospedada pode ser adicionado depois sem tocar no domínio nem na aplicação.

## Consequências

- Positivas: reproduzível, offline, grátis, CI rápido; troca de provedor isolada.
- Negativas: download de modelo no primeiro uso e imagem Docker maior; qualidade abaixo de modelos hospedados grandes (aceitável para um corpus pequeno e jargão restrito, coberto pela busca lexical).
