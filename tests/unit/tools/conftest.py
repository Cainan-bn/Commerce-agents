"""Fixtures unitárias do executor: transporte sem loja real, para medir requisições."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore
from tests.fakes.http import RecordingTransport


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
def transport() -> RecordingTransport:
    """Qualquer requisição à loja responde 500, para que a contagem em `requests` seja a prova."""

    def _store_should_not_answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "loja não deveria ser chamada"})

    return RecordingTransport(httpx.MockTransport(_store_should_not_answer))


@pytest.fixture
def unit_client(transport: RecordingTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, base_url="http://store")


@pytest.fixture
def make_unit_executor(
    unit_client: httpx.AsyncClient,
    tokens: InMemoryTokenStore,
    idempotency: InMemoryIdempotencyRegistry,
    sleep: Callable[[float], Awaitable[None]],
) -> Callable[..., Any]:
    from tests.fakes.tools import build_executor

    def _make(**options: Any) -> Any:
        return build_executor(
            client=options.pop("client", unit_client),
            tokens=options.pop("tokens", tokens),
            idempotency=options.pop("idempotency", idempotency),
            sleep=options.pop("sleep", sleep),
            **options,
        )

    return _make
