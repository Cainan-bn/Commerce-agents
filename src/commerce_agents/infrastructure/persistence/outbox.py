"""Outbox transacional e relay para o broker (ADR 0014)."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.ports.messaging import EventBus
from commerce_agents.infrastructure.messaging.topics import decode_event
from commerce_agents.infrastructure.persistence.models import OutboxModel
from commerce_agents.infrastructure.telemetry import current_traceparent, outbox_publish_span


class SqlOutboxRepository:
    """Implementa `OutboxRepository`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, topic: str, key: str, event: StrictModel) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                OutboxModel(
                    topic=topic,
                    key=key,
                    payload_json=event.model_dump_json(),
                    created_at=datetime.now(UTC),
                    traceparent=current_traceparent(),
                )
            )


class SqlOutboxRelay:
    """Implementa `OutboxRelay`. Falha do bus desfaz a marcação: a linha segue pendente."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], bus: EventBus) -> None:
        self._session_factory = session_factory
        self._bus = bus

    async def publish_pending(self, batch_size: int = 100) -> int:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        select(OutboxModel)
                        .where(OutboxModel.published_at.is_(None))
                        .order_by(OutboxModel.id)
                        .limit(batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                with outbox_publish_span(row.traceparent):
                    await self._bus.publish(row.topic, row.key, decode_event(row.payload_json))
                await session.execute(
                    update(OutboxModel)
                    .where(OutboxModel.id == row.id)
                    .values(published_at=datetime.now(UTC))
                )
            return len(rows)
