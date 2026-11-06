"""Sobe um servidor MCP (stdio): ``python -m commerce_agents.infrastructure.mcp <servidor>``."""

from __future__ import annotations

import argparse
import os

import httpx

from commerce_agents.infrastructure.mcp.executor import ToolExecutor
from commerce_agents.infrastructure.mcp.memory import (
    InMemoryIdempotencyRegistry,
    InMemoryTokenStore,
)
from commerce_agents.infrastructure.mcp.servers import ServerName, build_server

DEFAULT_STORE_BASE_URL = "http://localhost:8001"
SERVERS: tuple[ServerName, ...] = ("orders", "catalog", "shipping", "returns")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="commerce_agents.infrastructure.mcp")
    parser.add_argument("server", choices=SERVERS)
    parser.add_argument("--agent", required=True, help="Agente dono da sessão (allowlist)")
    args = parser.parse_args(argv)

    base_url = os.environ.get("STORE_BASE_URL") or DEFAULT_STORE_BASE_URL
    executor = ToolExecutor(
        client=httpx.AsyncClient(base_url=base_url),
        tokens=InMemoryTokenStore(),
        idempotency=InMemoryIdempotencyRegistry(),
    )
    build_server(args.server, executor, lambda: str(args.agent)).run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
