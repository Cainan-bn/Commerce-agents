"""Contadores no lugar de engine, embedder e retriever (SharedInfra) para testes sem Postgres."""

from dataclasses import dataclass, field
from typing import Any

import pytest


class FakeEngine:
    def __init__(self, counts: "Counts") -> None:
        self._counts = counts

    async def dispose(self) -> None:
        self._counts.disposed += 1


@dataclass
class Counts:
    engines: int = 0
    embedders: int = 0
    retrievers: int = 0
    disposed: int = 0
    deps: list[Any] = field(default_factory=list)


def install_counting_infra(monkeypatch: pytest.MonkeyPatch) -> Counts:
    """Troca engine, embedder e retriever por contadores nos módulos de origem e no harness."""
    from evals import harness

    from commerce_agents.infrastructure.persistence import database, migrate
    from commerce_agents.infrastructure.rag import embedder, retriever

    counts = Counts()

    def fake_create_engine(*args: Any, **kwargs: Any) -> FakeEngine:
        counts.engines += 1
        return FakeEngine(counts)

    class FakeEmbedder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            counts.embedders += 1

    class FakeRetriever:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            counts.retrievers += 1

    fakes = {
        "create_engine": fake_create_engine,
        "create_session_factory": lambda engine: object(),
        "sync_url_from_env": lambda: "postgresql+psycopg://u:p@localhost/db",
        "FastEmbedEmbedder": FakeEmbedder,
        "HybridPolicyRetriever": FakeRetriever,
    }
    origem = {
        "create_engine": database,
        "create_session_factory": database,
        "sync_url_from_env": migrate,
        "FastEmbedEmbedder": embedder,
        "HybridPolicyRetriever": retriever,
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(origem[name], name, fake)
        monkeypatch.setattr(harness, name, fake, raising=False)
    return counts
