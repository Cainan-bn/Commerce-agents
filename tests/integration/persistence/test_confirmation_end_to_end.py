"""Executor, mock_store ASGI e adaptadores Sql: token emitido e consumido em outra instância."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from commerce_agents.application.dto.tools import CancelOrderOutput
from commerce_agents.infrastructure.persistence.database import create_session_factory
from tests.fakes.clock import FakeClock
from tests.fakes.tools import (
    SEED_DIR,
    STORE_URL,
    build_executor,
    irreversible_arguments,
    issue_token,
)
from tests.integration.persistence.confirmation_helpers import new_engine_for

pytestmark = pytest.mark.integration

ENV_VARS = ("DATA_DIR", "MOCK_LATENCY_MS", "MOCK_ERROR_RATE", "MOCK_SEED", "MOCK_TODAY")


async def _no_sleep(delay: float) -> None:
    return None


@pytest.fixture
def store_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    from mock_store.main import create_app

    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOCK_TODAY", "2026-11-01T00:00:00Z")
    return create_app(SEED_DIR)


@pytest_asyncio.fixture
async def two_processes(engine_and_factory, store_app: Any) -> AsyncIterator[dict[str, Any]]:
    """Dois engines para o mesmo banco: o emissor e o servidor MCP (processos distintos)."""
    engine, factory = engine_and_factory
    other_engine = new_engine_for(engine)
    try:
        yield {
            "engine": engine,
            "other_factory": create_session_factory(other_engine),
            "factory": factory,
        }
    finally:
        await other_engine.dispose()


async def test_token_emitido_por_um_processo_e_consumido_por_outro_e_replay(
    two_processes: dict[str, Any], store_app: Any
):
    from commerce_agents.infrastructure.persistence.idempotency import SqlIdempotencyRegistry
    from commerce_agents.infrastructure.persistence.token_store import SqlConfirmationTokenStore

    clock = FakeClock()
    issuer = SqlConfirmationTokenStore(two_processes["factory"], clock=clock)
    server_tokens = SqlConfirmationTokenStore(two_processes["other_factory"], clock=clock)
    server_idempotency = SqlIdempotencyRegistry(two_processes["other_factory"])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=store_app), base_url=STORE_URL)
    executor = build_executor(
        client=client, tokens=server_tokens, idempotency=server_idempotency, sleep=_no_sleep
    )
    token = await issue_token(issuer, "cancel_order", {"order_id": "O000014"})
    arguments = irreversible_arguments("cancel_order", token, "idem-e2e-000001", order_id="O000014")

    first = await executor.invoke("Pedidos", "cancel_order", arguments)
    replay = await executor.invoke("Pedidos", "cancel_order", arguments)

    assert isinstance(first, CancelOrderOutput)
    assert replay == first
    assert store_app.state.store.orders["O000014"].status == "cancelled"
    assert await issuer.consume(token, "conv-test-1", "cancel_order", _digest()) is False
    await client.aclose()


def _digest() -> str:
    from commerce_agents.application.dto.tools import action_digest

    return action_digest("cancel_order", {"order_id": "O000014"})
