"""SqlDeliveryLedger contra Postgres real: entrega idempotente entre processos e purga."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect, text

from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.persistence.database import create_session_factory
from commerce_agents.infrastructure.persistence.migrate import downgrade_to_base, upgrade_to_head
from tests.integration.persistence.confirmation_helpers import new_engine_for

pytestmark = pytest.mark.integration


def _ledger(factory: Any) -> Any:
    from commerce_agents.infrastructure.persistence.delivery_ledger import SqlDeliveryLedger

    return SqlDeliveryLedger(factory)


def test_migracao_cria_e_remove_delivered_messages(migration_sync_url: str) -> None:
    upgrade_to_head(migration_sync_url)
    engine = create_engine(migration_sync_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("delivered_messages")
        columns = {column["name"] for column in inspector.get_columns("delivered_messages")}
        assert {"message_id", "channel", "delivered_at"} <= columns
        assert inspector.get_pk_constraint("delivered_messages")["constrained_columns"] == [
            "message_id"
        ]

        downgrade_to_base(migration_sync_url)
        assert not inspect(engine).has_table("delivered_messages")
    finally:
        engine.dispose()


async def test_ausente_depois_marcada(engine_and_factory):
    _, factory = engine_and_factory
    ledger = _ledger(factory)

    assert await ledger.was_delivered("reply:sql-1") is False
    await ledger.mark_delivered("reply:sql-1", Channel.WHATSAPP)

    assert await ledger.was_delivered("reply:sql-1") is True


async def test_grava_o_canal(engine_and_factory):
    engine, factory = engine_and_factory
    await _ledger(factory).mark_delivered("reply:sql-2", Channel.INSTAGRAM)

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT channel, delivered_at FROM delivered_messages WHERE message_id = :m"),
                {"m": "reply:sql-2"},
            )
        ).one()

    assert row.channel == Channel.INSTAGRAM.value
    assert row.delivered_at is not None


async def test_marcar_duas_vezes_nao_falha(engine_and_factory):
    _, factory = engine_and_factory
    ledger = _ledger(factory)

    await ledger.mark_delivered("reply:sql-3", Channel.WHATSAPP)
    await ledger.mark_delivered("reply:sql-3", Channel.WHATSAPP)

    assert await ledger.was_delivered("reply:sql-3") is True


async def test_marcar_concorrente_nao_levanta(engine_and_factory):
    engine, factory = engine_and_factory
    ledger = _ledger(factory)

    await asyncio.gather(
        *(ledger.mark_delivered("reply:sql-4", Channel.WHATSAPP) for _ in range(10))
    )

    async with engine.connect() as connection:
        count = (
            await connection.execute(
                text("SELECT count(*) FROM delivered_messages WHERE message_id = 'reply:sql-4'")
            )
        ).scalar_one()
    assert count == 1


async def test_persiste_entre_instancias_e_engines(engine_and_factory):
    engine, factory = engine_and_factory
    await _ledger(factory).mark_delivered("reply:sql-5", Channel.WHATSAPP)

    other_engine = new_engine_for(engine)
    try:
        other = _ledger(create_session_factory(other_engine))

        assert await other.was_delivered("reply:sql-5") is True
    finally:
        await other_engine.dispose()


async def test_purge_apaga_so_entregas_anteriores_ao_corte(engine_and_factory):
    _, factory = engine_and_factory
    ledger = _ledger(factory)
    await ledger.mark_delivered("reply:sql-6", Channel.WHATSAPP)
    now = datetime.now(UTC)

    assert await ledger.purge(now - timedelta(days=1)) == 0
    assert await ledger.was_delivered("reply:sql-6") is True

    assert await ledger.purge(now + timedelta(days=1)) == 1
    assert await ledger.was_delivered("reply:sql-6") is False
