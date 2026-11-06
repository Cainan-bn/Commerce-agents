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


def _customer_question(scenario: dict[str, Any]) -> str:
    """Primeiro turno do cliente: o que o agente em produção recebe (decisão do Líder)."""
    return str(scenario["turns"][0])


def _hit(texts: list[str], must_mention: list[str]) -> bool:
    haystack = " ".join(texts).lower()
    return any(str(term).lower() in haystack for term in must_mention)


def _reciprocal_rank(texts: list[str], must_mention: list[str]) -> float:
    for position, text in enumerate(texts, start=1):
        if _hit([text], must_mention):
            return 1 / position
    return 0.0


async def _evaluate(
    retriever: Any,
    scenarios: list[dict[str, Any]],
    query_of: Any,
    label: str,
) -> tuple[float, float]:
    hits = 0
    reciprocal_ranks: list[float] = []
    for scenario in scenarios:
        query = query_of(scenario)
        must = scenario["expected"]["must_mention"]
        chunks = await retriever.retrieve(query, k=K)
        texts = [chunk.text for chunk in chunks]
        hit = _hit(texts, must)
        hits += int(hit)
        reciprocal_ranks.append(_reciprocal_rank(texts, must))
        ranking = [f"{c.chunk_id}" for c in chunks]
        print(f"[{label}] {scenario['id']} hit={hit} ranking={ranking} query={query!r}")
    recall = hits / len(scenarios)
    mrr = sum(reciprocal_ranks) / len(scenarios)
    print(f"[{label}] recall@{K}={recall:.3f} MRR={mrr:.3f} (n={len(scenarios)})")
    return recall, mrr


async def test_recall_at_4_e_mrr_com_pergunta_do_cliente(rag_db):
    from commerce_agents.infrastructure.rag.embedder import FastEmbedEmbedder
    from commerce_agents.infrastructure.rag.ingestion import PolicyIngestor
    from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever

    _, factory = rag_db
    embedder = FastEmbedEmbedder()
    await PolicyIngestor(factory, embedder).ingest(POLICIES_DIR)
    retriever = HybridPolicyRetriever(factory, embedder)
    scenarios = _pol_scenarios()

    # Métrica principal: consulta = primeiro turno do cliente. Limiar e MRR são asserted/impressos.
    recall, mrr = await _evaluate(retriever, scenarios, _customer_question, "pergunta")
    assert recall >= RECALL_THRESHOLD, f"recall@{K}={recall:.3f} < {RECALL_THRESHOLD}"
    assert 0.0 <= mrr <= 1.0

    # Métrica secundária (somente impressa, sem assert): consulta = args.query de uma palavra.
    await _evaluate(retriever, scenarios, _search_query, "args.query")


def test_todos_os_cenarios_pol_tem_pergunta_do_cliente():
    """A métrica principal depende de turns[0] não vazio em cada cenário POL-*."""
    assert all(_customer_question(scenario).strip() for scenario in _pol_scenarios())


OUT_OF_DOMAIN_QUERIES = [
    "receita de bolo",
    "previsao do tempo em Lisboa",
    "como instalar python",
]


async def test_consultas_fora_de_dominio_devolvem_lista_vazia(rag_db):
    from commerce_agents.infrastructure.rag.embedder import FastEmbedEmbedder
    from commerce_agents.infrastructure.rag.ingestion import PolicyIngestor
    from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever

    _, factory = rag_db
    embedder = FastEmbedEmbedder()
    await PolicyIngestor(factory, embedder).ingest(POLICIES_DIR)
    # min_dense_similarity fica no DEFAULT do retriever: o CORE calibra o limiar com o modelo real.
    retriever = HybridPolicyRetriever(factory, embedder)

    for query in OUT_OF_DOMAIN_QUERIES:
        assert await retriever.retrieve(query, k=K) == [], query
