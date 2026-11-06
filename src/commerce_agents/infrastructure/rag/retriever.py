"""Recuperação híbrida de políticas: lexical + denso + RRF (ADR 0005, docs/architecture/rag.md).

O texto recuperado é dado, nunca instrução (ADR 0010): nada aqui interpreta o conteúdo.
"""

from __future__ import annotations

import math
import re

from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.application.dto.views import PolicyChunk
from commerce_agents.application.ports.embeddings import Embedder
from commerce_agents.application.rag.fusion import DEFAULT_RRF_K, rrf_fuse
from commerce_agents.infrastructure.persistence.models import PolicyChunkModel
from commerce_agents.infrastructure.rag.reranker import NullReranker, Reranker

MAX_QUERY_CHARS = 300


class HybridPolicyRetriever:
    """Implementa ``PolicyRetriever`` sobre ``policy_chunks``."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        *,
        candidates: int = 20,
        rrf_k: int = DEFAULT_RRF_K,
        min_dense_similarity: float = 0.45,
        reranker: Reranker | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._candidates = candidates
        self._rrf_k = rrf_k
        self._min_dense_similarity = min_dense_similarity
        self._reranker: Reranker = reranker or NullReranker()

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyChunk]:
        text = query.strip()
        if not text or len(text) > MAX_QUERY_CHARS:
            raise ValueError(f"A consulta deve ter de 1 a {MAX_QUERY_CHARS} caracteres.")
        vector = await self._embedder.embed_query(text)
        async with self._session_factory() as session, session.begin():
            lexical = await self._lexical(session, text)
            dense = await self._dense(session, vector)
            fused = rrf_fuse([lexical, dense], k=self._rrf_k)[:k]
            if not fused:
                return []
            rows = {
                row.chunk_id: row
                for row in (
                    await session.execute(
                        select(PolicyChunkModel).where(
                            PolicyChunkModel.chunk_id.in_([cid for cid, _ in fused])
                        )
                    )
                ).scalars()
            }
        chunks = [
            PolicyChunk(
                chunk_id=chunk_id,
                document=rows[chunk_id].document,
                section=rows[chunk_id].section,
                text=rows[chunk_id].text,
                score=score,
                corpus_version=rows[chunk_id].corpus_version,
            )
            for chunk_id, score in fused
        ]
        return await self._reranker.rerank(text, chunks)

    async def _lexical(self, session: AsyncSession, query: str) -> list[str]:
        and_query = func.websearch_to_tsquery("portuguese", func.public.immutable_unaccent(query))
        ids = await self._ranked_ids(session, and_query)
        if ids:
            return ids
        return await self._lexical_or(session, query)

    async def _lexical_or(self, session: AsyncSession, query: str) -> list[str]:
        """Fallback OR: exige que ao menos metade dos termos relevantes case no trecho.

        Sem esse piso, uma palavra comum ("tempo") faria consultas fora de domínio acharem
        trechos irrelevantes. Stopwords (``numnode = 0``) não contam como termo.
        """
        terms = list(dict.fromkeys(re.findall(r"\w+", query.lower())))
        if not terms:
            return []
        queries = [func.to_tsquery("portuguese", func.public.immutable_unaccent(t)) for t in terms]
        sizes = (await session.execute(select(*[func.numnode(q) for q in queries]))).one()
        relevant = [
            q for q, size in zip(queries, sizes, strict=True) if isinstance(size, int) and size > 0
        ]
        if not relevant:
            return []
        matched = sum(
            (case((PolicyChunkModel.search_vector.op("@@")(q), 1), else_=0) for q in relevant),
            start=literal(0),
        )
        or_query = func.to_tsquery("portuguese", func.public.immutable_unaccent(" | ".join(terms)))
        rank = func.ts_rank_cd(PolicyChunkModel.search_vector, or_query)
        result = await session.execute(
            select(PolicyChunkModel.chunk_id)
            .where(PolicyChunkModel.search_vector.op("@@")(or_query))
            .where(matched >= math.ceil(len(relevant) / 2))
            .order_by(rank.desc(), PolicyChunkModel.chunk_id)
            .limit(self._candidates)
        )
        return list(result.scalars())

    async def _ranked_ids(self, session: AsyncSession, tsquery: object) -> list[str]:
        rank = func.ts_rank_cd(PolicyChunkModel.search_vector, tsquery)
        result = await session.execute(
            select(PolicyChunkModel.chunk_id)
            .where(PolicyChunkModel.search_vector.op("@@")(tsquery))
            .order_by(rank.desc(), PolicyChunkModel.chunk_id)
            .limit(self._candidates)
        )
        return list(result.scalars())

    async def _dense(self, session: AsyncSession, vector: list[float]) -> list[str]:
        distance = PolicyChunkModel.embedding.cosine_distance(vector)
        result = await session.execute(
            select(PolicyChunkModel.chunk_id, (1 - distance).label("similarity"))
            .order_by(distance, PolicyChunkModel.chunk_id)
            .limit(self._candidates)
        )
        return [row.chunk_id for row in result if row.similarity >= self._min_dense_similarity]
