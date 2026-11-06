# 0012. Embeddings locais (fastembed, paraphrase-multilingual-MiniLM-L12-v2) atrás de um port

- Status: Accepted
- Data: 2026-11-06
- Complementa: ADR 0005, ADR 0007

## Contexto e problema

O RAG híbrido (ADR 0005) precisa de embeddings em português. O projeto roda em WSL2, com CI gratuito e sem garantia de chave de API; o corpus tem dezenas de trechos e a ingestão deve ser reproduzível.

## Opções consideradas

1. API hospedada (OpenAI/Cohere/Voyage): melhor qualidade bruta, mas exige chave, rede e custo em cada ingestão e em cada consulta; acopla CI a um terceiro.
2. Modelo local via `fastembed` (ONNX) com um modelo multilíngue (384 dims): offline após o download, determinístico, sem custo; cold start. O `fastembed` 0.9 não suporta `multilingual-e5-small` (só o `large`, 1024 dims, 2,2 GB); escolhido `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dims, 0,22 GB), que mantém a coluna `vector(384)`.
3. `sentence-transformers` (PyTorch): mesma ideia, dependência muito mais pesada.

## Decisão

Opção 2, atrás do port `Embedder` (`embed_documents`, `embed_query`, `dimension`, `model_name`). Detalhes:

- O modelo MiniLM não usa prefixos; se o modelo mudar para uma família que use (e5), o prefixo fica dentro do adaptador.
- A coluna é `vector(384)` com índice HNSW (cosseno). Trocar de modelo exige nova migration e reingestão; `model_name` é gravado por chunk e a ingestão reindexa tudo quando o modelo mudar.
- Testes padrão usam um `HashingEmbedder` determinístico (bag-of-words por hash) que valida a mecânica (RRF, idempotência, SQL); a qualidade semântica é medida num alvo separado `make eval-rag` (recall@k com o modelo real, marcador `embeddings`), fora do CI padrão para não depender de download.
- Um adaptador de API hospedada pode ser adicionado depois sem tocar no domínio nem na aplicação.

## Consequências

- Positivas: reproduzível, offline, grátis, CI rápido; troca de provedor isolada.
- Negativas: download de modelo no primeiro uso e imagem Docker maior; qualidade abaixo de modelos hospedados grandes (aceitável para um corpus pequeno e jargão restrito, coberto pela busca lexical).
