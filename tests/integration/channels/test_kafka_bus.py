"""KafkaEventBus e consume (ADR 0006/0014) no Redpanda: ordem por chave e commit após handler."""

import asyncio
import uuid
from typing import Any

import pytest

from commerce_agents.application.dto.events import HandoffRequested
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration


def _event(n: int) -> HandoffRequested:
    from datetime import UTC, datetime

    return HandoffRequested(
        conversation_id="web:s1",
        reason=f"motivo {n}",
        priority="normal",
        summary="resumo",
        requested_at=datetime(2026, 11, 6, 12, 0, n, tzinfo=UTC),
    )


async def test_mensagens_da_mesma_chave_chegam_em_ordem(redpanda_bootstrap: str):
    from commerce_agents.infrastructure.messaging.bus import KafkaEventBus, consume

    topic = f"test.order.{uuid.uuid4().hex[:8]}"
    bus = KafkaEventBus(redpanda_bootstrap)
    for n in range(3):
        await bus.publish(topic, "web:s1", _event(n))
    received: list[str] = []

    async def handler(event: Any) -> None:
        received.append(event.reason)

    task = asyncio.create_task(
        consume(redpanda_bootstrap, topic, f"g-{uuid.uuid4().hex[:6]}", handler)
    )
    await asyncio.wait_for(_until(lambda: len(received) == 3), timeout=60)
    task.cancel()

    assert received == ["motivo 0", "motivo 1", "motivo 2"]


async def test_handler_que_falha_nao_confirma_offset_e_reentrega(redpanda_bootstrap: str):
    from commerce_agents.infrastructure.messaging.bus import KafkaEventBus, consume

    topic = f"test.retry.{uuid.uuid4().hex[:8]}"
    group = f"g-{uuid.uuid4().hex[:6]}"
    bus = KafkaEventBus(redpanda_bootstrap)
    await bus.publish(topic, "web:s1", _event(1))
    attempts: list[int] = []

    async def failing(event: Any) -> None:
        attempts.append(1)
        raise RuntimeError("handler falhou")

    task = asyncio.create_task(consume(redpanda_bootstrap, topic, group, failing))
    await asyncio.wait_for(_until(lambda: len(attempts) >= 2), timeout=90)
    task.cancel()

    assert len(attempts) >= 2


async def _until(predicate: Any) -> None:
    while not predicate():
        await asyncio.sleep(0.1)
