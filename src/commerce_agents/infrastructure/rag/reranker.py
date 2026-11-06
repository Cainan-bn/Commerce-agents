"""Reranker opcional (feature flag ``RAG_RERANKER_ENABLED``, desligada por padrão)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from commerce_agents.application.dto.views import PolicyChunk


class Reranker(Protocol):
    async def rerank(self, query: str, chunks: Sequence[PolicyChunk]) -> list[PolicyChunk]: ...


class NullReranker:
    """Preserva a ordem recebida."""

    async def rerank(self, query: str, chunks: Sequence[PolicyChunk]) -> list[PolicyChunk]:
        return list(chunks)
