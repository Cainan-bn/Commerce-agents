"""Outbox e relay (ADR 0014): ordem, publicação idempotente, falha do bus e UNIQUE de resposta."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from commerce_agents.application.dto.channels import TOPIC_OUTBOUND, OutboundMessageReady
from commerce_agents.domain.conversation.channel import Channel
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _msg(n: int) -> OutboundMessageReady:
    return OutboundMessageReady(
        message_id=f"reply:wamid.O{n}",
        conversation_id="web:s1",
        channel=Channel.WEB,
        recipient_external_id="s1",
        text=f"mensagem {n}",
        source="agent",
        created_at=AT,
    )


class RecordingBus:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, Any]] = []

    async def publish(self, topic: str, key: str, event: Any) -> None:
        if self.fail:
            raise ConnectionError("broker fora do ar")
        self.published.append((topic, key, event))


def _outbox(factory):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.persistence.outbox import (
        SqlOutboxRelay,
        SqlOutboxRepository,
    )

    return SqlOutboxRepository(factory), SqlOutboxRelay


async def test_relay_publica_pendentes_na_ordem_e_marca_published(channels_db):
    engine, factory = channels_db
    repo, relay_cls = _outbox(factory)
    for n in range(3):
        await repo.add(TOPIC_OUTBOUND, "web:s1", _msg(n))
    bus = RecordingBus()

    published = await relay_cls(factory, bus).publish_pending()

    assert published == 3
    assert [event.text for _, _, event in bus.published] == [
        "mensagem 0",
        "mensagem 1",
        "mensagem 2",
    ]
    async with engine.connect() as connection:
        pending = (
            await connection.execute(text("SELECT count(*) FROM outbox WHERE published_at IS NULL"))
        ).scalar_one()
    assert pending == 0


async def test_relay_e_idempotente(channels_db):
    _, factory = channels_db
    repo, relay_cls = _outbox(factory)
    await repo.add(TOPIC_OUTBOUND, "web:s1", _msg(9))
    bus = RecordingBus()
    relay = relay_cls(factory, bus)

    await relay.publish_pending()
    second = await relay.publish_pending()

    assert second == 0
    assert len(bus.published) == 1


async def test_falha_do_bus_deixa_linha_pendente(channels_db):
    engine, factory = channels_db
    repo, relay_cls = _outbox(factory)
    await repo.add(TOPIC_OUTBOUND, "web:s1", _msg(7))

    with pytest.raises(ConnectionError):
        await relay_cls(factory, RecordingBus(fail=True)).publish_pending()

    async with engine.connect() as connection:
        pending = (
            await connection.execute(text("SELECT count(*) FROM outbox WHERE published_at IS NULL"))
        ).scalar_one()
    assert pending == 1


async def test_unique_de_inbound_message_id_evita_resposta_duplicada(channels_db):
    engine, factory = channels_db
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO outbox (topic, key, payload_json, inbound_message_id, created_at) "
                "VALUES ('outbound.messages', 'k', '{}', 'wamid.DUP', now())"
            )
        )

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO outbox (topic, key, payload_json, inbound_message_id, created_at) "
                    "VALUES ('outbound.messages', 'k', '{}', 'wamid.DUP', now())"
                )
            )
