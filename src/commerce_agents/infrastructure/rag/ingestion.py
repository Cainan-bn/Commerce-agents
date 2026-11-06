"""Ingestão idempotente de ``data/policies`` no Postgres (docs/architecture/rag.md)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.application.dto.rag import Chunk, IngestionReport
from commerce_agents.application.ports.embeddings import Embedder
from commerce_agents.application.rag.chunking import chunk_document, corpus_version, indexed_text
from commerce_agents.infrastructure.persistence.models import PolicyChunkModel


def load_chunks(policies_dir: Path) -> list[Chunk]:
    """Lê e divide todos os ``*.md`` do diretório, em ordem alfabética."""
    chunks: list[Chunk] = []
    for policy in sorted(policies_dir.glob("*.md")):
        chunks.extend(chunk_document(policy.stem, policy.read_text(encoding="utf-8")))
    return chunks


class PolicyIngestor:
    """Indexa só o que mudou (hash do conteúdo + modelo), numa única transação."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], embedder: Embedder
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    async def ingest(self, policies_dir: Path) -> IngestionReport:
        chunks = load_chunks(policies_dir)
        version = corpus_version(chunks)
        model_name = self._embedder.model_name
        async with self._session_factory() as session, session.begin():
            existing = {
                row.chunk_id: (row.content_hash, row.model_name)
                for row in await session.execute(
                    select(
                        PolicyChunkModel.chunk_id,
                        PolicyChunkModel.content_hash,
                        PolicyChunkModel.model_name,
                    )
                )
            }
            added = [c for c in chunks if c.chunk_id not in existing]
            updated = [
                c
                for c in chunks
                if c.chunk_id in existing and existing[c.chunk_id] != (c.content_hash, model_name)
            ]
            removed = set(existing) - {c.chunk_id for c in chunks}
            to_embed = [*added, *updated]
            vectors = await self._embedder.embed_documents([indexed_text(c) for c in to_embed])
            for chunk, vector in zip(to_embed, vectors, strict=True):
                await session.execute(self._upsert(chunk, vector, model_name, version))
            if removed:
                await session.execute(
                    delete(PolicyChunkModel).where(PolicyChunkModel.chunk_id.in_(removed))
                )
            await session.execute(
                update(PolicyChunkModel)
                .where(PolicyChunkModel.corpus_version != version)
                .values(corpus_version=version)
            )
        return IngestionReport(
            corpus_version=version,
            model_name=model_name,
            chunks_total=len(chunks),
            chunks_added=len(added),
            chunks_updated=len(updated),
            chunks_removed=len(removed),
            chunks_unchanged=len(chunks) - len(added) - len(updated),
            embeddings_computed=len(to_embed),
        )

    @staticmethod
    def _upsert(chunk: Chunk, vector: list[float], model_name: str, version: str):  # type: ignore[no-untyped-def]
        values = {
            "chunk_id": chunk.chunk_id,
            "document": chunk.document,
            "title": chunk.title,
            "section": chunk.section,
            "position": chunk.position,
            "text": chunk.text,
            "content_hash": chunk.content_hash,
            "model_name": model_name,
            "corpus_version": version,
            "embedding": vector,
        }
        insert = pg_insert(PolicyChunkModel).values(**values)
        return insert.on_conflict_do_update(
            index_elements=[PolicyChunkModel.chunk_id],
            set_={
                **{k: insert.excluded[k] for k in values if k != "chunk_id"},
                "updated_at": func.now(),
            },
        )
