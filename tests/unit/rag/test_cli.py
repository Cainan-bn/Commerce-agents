"""CLI do RAG: ingest (padrão) e query, com os adaptadores substituídos."""

from typing import Any

import pytest

from commerce_agents.application.dto.rag import IngestionReport
from commerce_agents.application.dto.views import PolicyChunk
from commerce_agents.infrastructure.rag import __main__ as cli

pytestmark = pytest.mark.unit


class _Engine:
    disposed = False

    async def dispose(self) -> None:
        _Engine.disposed = True


class _Ingestor:
    def __init__(self, factory: Any, embedder: Any) -> None: ...

    async def ingest(self, policies_dir: Any) -> IngestionReport:
        return IngestionReport(
            corpus_version="abc",
            model_name="m",
            chunks_total=1,
            chunks_added=1,
            chunks_updated=0,
            chunks_removed=0,
            chunks_unchanged=0,
            embeddings_computed=1,
        )


class _Retriever:
    def __init__(self, factory: Any, embedder: Any) -> None: ...

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyChunk]:
        return [
            PolicyChunk(
                chunk_id="troca#0",
                document="troca",
                section="Prazo",
                text="7 dias",
                score=0.5,
                corpus_version="abc",
            )
        ]


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    _Engine.disposed = False
    monkeypatch.setattr(cli, "create_engine", lambda url: _Engine())
    monkeypatch.setattr(cli, "create_session_factory", lambda engine: object())
    monkeypatch.setattr(cli, "FastEmbedEmbedder", lambda: object())
    monkeypatch.setattr(cli, "PolicyIngestor", _Ingestor)
    monkeypatch.setattr(cli, "HybridPolicyRetriever", _Retriever)


def test_sem_subcomando_faz_ingest(capsys: pytest.CaptureFixture[str]):
    cli.main([])

    assert '"corpus_version": "abc"' in capsys.readouterr().out
    assert _Engine.disposed


def test_query_imprime_trechos_com_fonte(capsys: pytest.CaptureFixture[str]):
    cli.main(["query", "prazo", "-k", "2"])

    out = capsys.readouterr().out
    assert "troca#0 (Prazo)" in out
    assert "7 dias" in out
    assert _Engine.disposed
