"""SqlInboundLedger (ADR 0014): claim new/retry/done, concorrência e outbox na mesma transação."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _event(message_id: str = "wamid.L1") -> InboundMessageReceived:
    return InboundMessageReceived(
        message_id=message_id,
        conversation_id="whatsapp:5511900000001",
        channel=Channel.WHATSAPP,
        customer_external_id="5511900000001",
        text="oi",
        received_at=AT,
    )


def _reply(message_id: str = "reply:wamid.L1") -> OutboundMessageReady:
    return OutboundMessageReady(
        message_id=message_id,
        conversation_id="whatsapp:5511900000001",
        channel=Channel.WHATSAPP,
        recipient_external_id="5511900000001",
        text="Olá!",
        source="agent",
        created_at=AT,
    )


def _ledger(factory):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.persistence.inbound_ledger import SqlInboundLedger

    return SqlInboundLedger(factory)


async def test_claim_new_retry_e_done(channels_db):
    _, factory = channels_db
    ledger = _ledger(factory)

    assert await ledger.claim(_event()) == "new"
    assert await ledger.claim(_event()) == "retry"
    await ledger.complete("wamid.L1", _reply(), at=AT)
    assert await ledger.claim(_event()) == "done"


async def test_dez_claims_simultaneos_tem_um_new(channels_db):
    _, factory = channels_db
    ledger = _ledger(factory)

    results = await asyncio.gather(*(ledger.claim(_event("wamid.RACE")) for _ in range(10)))

    assert results.count("new") == 1


async def test_falha_no_insert_do_outbox_nao_marca_done(channels_db):
    engine, factory = channels_db
    ledger = _ledger(factory)
    await ledger.claim(_event("wamid.TXN"))
    # Injeta conflito no outbox: já existe linha com o mesmo inbound_message_id (UNIQUE).
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO outbox (topic, key, payload_json, inbound_message_id, created_at) "
                "VALUES ('outbound.messages', 'k', '{}', 'wamid.TXN', now())"
            )
        )

    with pytest.raises(IntegrityError):
        await ledger.complete("wamid.TXN", _reply("reply:wamid.TXN"), at=AT)

    assert await ledger.claim(_event("wamid.TXN")) == "retry"
