"""Recall@4 e MRR do RAG com o modelo real (ADR 0012); marcador `embeddings`, fora do make test."""

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.embeddings

ROOT = Path(__file__).resolve().parents[2]
POLICIES_DIR = ROOT / "data" / "policies"
SCENARIOS_DIR = ROOT / "data" / "eval_scenarios"
RECALL_THRESHOLD = 0.9
K = 4


def _pol_scenarios() -> list[dict[str, Any]]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("POL-*.yaml")):
        scenarios.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return scenarios


def _search_query(scenario: dict[str, Any]) -> str:
    tool = next(t for t in scenario["expected"]["tools"] if t["name"] == "search_policies")
    return str(tool["args"]["query"])


def _hit(texts: list[str], must_mention: list[str]) -> bool:
    haystack = " ".join(texts).lower()
    return any(str(term).lower() in haystack for term in must_mention)


def _reciprocal_rank(texts: list[str], must_mention: list[str]) -> float:
    for position, text in enumerate(texts, start=1):
        if _hit([text], must_mention):
            return 1 / position
    return 0.0


async def test_recall_at_4_e_mrr_com_modelo_real(rag_db, capsys: pytest.CaptureFixture[str]):
    from commerce_agents.infrastructure.rag.embedder import FastEmbedEmbedder
    from commerce_agents.infrastructure.rag.ingestion import PolicyIngestor
    from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever

    _, factory = rag_db
    embedder = FastEmbedEmbedder()
    await PolicyIngestor(factory, embedder).ingest(POLICIES_DIR)
    retriever = HybridPolicyRetriever(factory, embedder)

    hits = 0
    reciprocal_ranks: list[float] = []
    scenarios = _pol_scenarios()
    for scenario in scenarios:
        query = _search_query(scenario)
        must = scenario["expected"]["must_mention"]
        chunks = await retriever.retrieve(query, k=K)
        texts = [chunk.text for chunk in chunks]
        hit = _hit(texts, must)
        hits += int(hit)
        reciprocal_ranks.append(_reciprocal_rank(texts, must))
        print(f"{scenario['id']} hit={hit} query={query!r}")

    recall = hits / len(scenarios)
    mrr = sum(reciprocal_ranks) / len(scenarios)
    print(f"recall@{K}={recall:.3f} MRR={mrr:.3f} (n={len(scenarios)})")
    assert recall >= RECALL_THRESHOLD
