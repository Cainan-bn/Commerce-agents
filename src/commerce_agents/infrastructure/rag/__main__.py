"""CLI do RAG: ``python -m commerce_agents.infrastructure.rag [ingest|query <texto>]``."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from commerce_agents.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
)
from commerce_agents.infrastructure.persistence.migrate import sync_url_from_env
from commerce_agents.infrastructure.rag.embedder import FastEmbedEmbedder
from commerce_agents.infrastructure.rag.ingestion import PolicyIngestor
from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever

DEFAULT_POLICIES_DIR = "data/policies"


async def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="commerce_agents.infrastructure.rag")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("ingest", help="Indexa data/policies (padrão)")
    query = sub.add_parser("query", help="Consulta o índice")
    query.add_argument("text")
    query.add_argument("-k", type=int, default=4)
    args = parser.parse_args(argv)

    engine = create_engine(sync_url_from_env().replace("+psycopg", "+asyncpg"))
    factory = create_session_factory(engine)
    embedder = FastEmbedEmbedder()
    try:
        if args.command == "query":
            retriever = HybridPolicyRetriever(factory, embedder)
            for chunk in await retriever.retrieve(args.text, k=args.k):
                print(f"[{chunk.score:.4f}] {chunk.chunk_id} ({chunk.section})\n{chunk.text}\n")
        else:
            policies_dir = Path(os.environ.get("POLICIES_DIR", DEFAULT_POLICIES_DIR))
            report = await PolicyIngestor(factory, embedder).ingest(policies_dir)
            print(report.model_dump_json(indent=2))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(run(argv))


if __name__ == "__main__":  # pragma: no cover
    main()
