"""Fixtures dos testes de contrato do executor: mock_store real via ASGI, sem rede."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from mock_store.main import create_app

from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import MOCK_TODAY, STORE_URL, build_executor

ENV_VARS = (
    "DATA_DIR",
    "MOCK_LATENCY_MS",
    "MOCK_ERROR_RATE",
    "MOCK_SEED",
    "MOCK_TODAY",
)


@pytest.fixture
def store_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOCK_TODAY", MOCK_TODAY)
    return create_app()


@pytest.fixture
def transport(store_app: FastAPI) -> RecordingTransport:
    return RecordingTransport(httpx.ASGITransport(app=store_app))


@pytest.fixture
async def client(transport: RecordingTransport) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=transport, base_url=STORE_URL) as http_client:
        yield http_client


@pytest.fixture
def tokens() -> InMemoryTokenStore:
    return InMemoryTokenStore()


@pytest.fixture
def idempotency() -> InMemoryIdempotencyRegistry:
    return InMemoryIdempotencyRegistry()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def sleep(sleeps: list[float]) -> Callable[[float], Awaitable[None]]:
    async def _record(delay: float) -> None:
        sleeps.append(delay)

    return _record


@pytest.fixture
def make_executor(
    client: httpx.AsyncClient,
    tokens: InMemoryTokenStore,
    idempotency: InMemoryIdempotencyRegistry,
    sleep: Callable[[float], Awaitable[None]],
) -> Callable[..., Any]:
    def _make(**options: Any) -> Any:
        return build_executor(
            client=options.pop("client", client),
            tokens=options.pop("tokens", tokens),
            idempotency=options.pop("idempotency", idempotency),
            sleep=options.pop("sleep", sleep),
            **options,
        )

    return _make
