"""Ledger de entregas aos canais em Postgres: idempotência durável dos senders."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.persistence.models import DeliveredMessageModel


class SqlDeliveryLedger:
    """Implementa ``DeliveryLedger``; marcar de novo (ou em paralelo) não falha."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def was_delivered(self, message_id: str) -> bool:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(DeliveredMessageModel.message_id).where(
                        DeliveredMessageModel.message_id == message_id
                    )
                )
            ).first()
        return row is not None

    async def mark_delivered(self, message_id: str, channel: Channel) -> None:
        statement = (
            pg_insert(DeliveredMessageModel)
            .values(message_id=message_id, channel=channel.value)
            .on_conflict_do_nothing(index_elements=[DeliveredMessageModel.message_id])
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def purge(self, older_than: datetime) -> int:
        """Apaga entregas anteriores ao corte; devolve quantas saíram."""
        statement = (
            delete(DeliveredMessageModel)
            .where(DeliveredMessageModel.delivered_at < older_than)
            .returning(DeliveredMessageModel.message_id)
        )
        async with self._session_factory() as session, session.begin():
            return len((await session.execute(statement)).all())
