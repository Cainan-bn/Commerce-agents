"""Fixtures dos casos de uso de confirmação (ADR 0008 e 0011)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.invoker import FakeToolInvoker, RecordingPublisher

FIXED_KEY = "idem-fixed-000001"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def tokens() -> InMemoryTokenStore:
    return InMemoryTokenStore()


@pytest.fixture
def make_propose(tokens: InMemoryTokenStore, clock: FakeClock) -> Callable[..., Any]:
    """Instancia ProposeIrreversibleAction do módulo alvo (import preguiçoso)."""

    def _make(**options: Any) -> Any:
        from commerce_agents.application.use_cases.irreversible import ProposeIrreversibleAction

        return ProposeIrreversibleAction(
            options.pop("tokens", tokens),
            clock=options.pop("clock", clock),
            new_key=options.pop("new_key", lambda: FIXED_KEY),
            **options,
        )

    return _make


@pytest.fixture
def make_confirm(clock: FakeClock) -> Callable[..., Any]:
    """Instancia ConfirmIrreversibleAction do módulo alvo (import preguiçoso)."""

    def _make(invoker: Any, publish: Any, **options: Any) -> Any:
        from commerce_agents.application.use_cases.irreversible import ConfirmIrreversibleAction

        return ConfirmIrreversibleAction(invoker, publish, clock=options.pop("clock", clock))

    return _make


@pytest.fixture
def log() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def invoker(log: list[tuple[str, str]]) -> FakeToolInvoker:
    return FakeToolInvoker(outcome=None, log=log)


@pytest.fixture
def publisher(log: list[tuple[str, str]]) -> RecordingPublisher:
    return RecordingPublisher(log=log)
