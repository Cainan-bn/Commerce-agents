"""Sobe um servidor MCP (stdio): ``python -m commerce_agents.infrastructure.mcp <servidor>``."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from commerce_agents.application.ports.confirmation import (
    ConfirmationTokenStore,
    IdempotencyRegistry,
)
from commerce_agents.infrastructure.mcp.executor import ToolExecutor
from commerce_agents.infrastructure.mcp.memory import (
    InMemoryIdempotencyRegistry,
    InMemoryTokenStore,
)
from commerce_agents.infrastructure.mcp.servers import ServerName, build_server
from commerce_agents.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
)
from commerce_agents.infrastructure.persistence.idempotency import SqlIdempotencyRegistry
from commerce_agents.infrastructure.persistence.migrate import sync_url_from_env
from commerce_agents.infrastructure.persistence.token_store import SqlConfirmationTokenStore

logger = logging.getLogger(__name__)

DEFAULT_STORE_BASE_URL = "http://localhost:8001"
SERVERS: tuple[ServerName, ...] = ("orders", "catalog", "shipping", "returns")


def _has_database(environ: Mapping[str, str]) -> bool:
    return any(name == "DATABASE_URL" or name.startswith("POSTGRES_") for name in environ)


def build_stores(
    environ: Mapping[str, str],
) -> tuple[ConfirmationTokenStore, IdempotencyRegistry]:
    """Token e idempotência em Postgres quando há banco configurado; senão, em memória (dev)."""
    if not _has_database(environ):
        logger.warning(
            "Sem DATABASE_URL/POSTGRES_*: token e idempotência em memória (apenas dev, não "
            "compartilhados com o orquestrador)."
        )
        return InMemoryTokenStore(), InMemoryIdempotencyRegistry()
    async_url = sync_url_from_env().replace("+psycopg", "+asyncpg")
    factory = create_session_factory(create_engine(async_url))
    return (
        SqlConfirmationTokenStore(factory, clock=lambda: datetime.now(UTC)),
        SqlIdempotencyRegistry(factory),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="commerce_agents.infrastructure.mcp")
    parser.add_argument("server", choices=SERVERS)
    parser.add_argument("--agent", required=True, help="Agente dono da sessão (allowlist)")
    args = parser.parse_args(argv)

    base_url = os.environ.get("STORE_BASE_URL") or DEFAULT_STORE_BASE_URL
    tokens, idempotency = build_stores(os.environ)
    executor = ToolExecutor(
        client=httpx.AsyncClient(base_url=base_url), tokens=tokens, idempotency=idempotency
    )
    build_server(args.server, executor, lambda: str(args.agent)).run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
