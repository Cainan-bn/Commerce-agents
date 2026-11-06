"""Bordas do fallback lexical: consulta sem termos e consulta só de stopwords."""

from pathlib import Path
from typing import Any

import pytest

from tests.fakes.hashing_embedder import HashingEmbedder

pytestmark = pytest.mark.integration

POLICIES_DIR = Path(__file__).resolve().parents[3] / "data" / "policies"


@pytest.mark.parametrize("query", ["???", "de em o"])
async def test_consulta_sem_termo_relevante_devolve_vazio(rag_db: Any, query: str):
    from commerce_agents.infrastructure.rag.ingestion import PolicyIngestor
    from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever

    _, factory = rag_db
    embedder = HashingEmbedder()
    await PolicyIngestor(factory, embedder).ingest(POLICIES_DIR)
    # limiar denso inalcançável: isola o caminho lexical
    retriever = HybridPolicyRetriever(factory, embedder, min_dense_similarity=1.1)

    assert await retriever.retrieve(query, k=4) == []
