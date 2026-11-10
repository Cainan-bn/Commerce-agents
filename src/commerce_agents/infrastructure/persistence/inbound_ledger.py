"""Ledger de mensagens recebidas em Postgres (ADR 0014)."""

from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.application.dto.channels import TOPIC_OUTBOUND, OutboundMessageReady
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.infrastructure.persistence.models import InboundMessageModel, OutboxModel
from commerce_agents.infrastructure.telemetry import current_traceparent


class SqlInboundLedger:
    """Implementa `InboundLedger`: claim por INSERT ... ON CONFLICT e complete transacional."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(self, event: InboundMessageReceived) -> Literal["new", "retry", "done"]:
        insert = (
            pg_insert(InboundMessageModel)
            .values(message_id=event.message_id, conversation_id=event.conversation_id)
            .on_conflict_do_nothing(index_elements=[InboundMessageModel.message_id])
            .returning(InboundMessageModel.message_id)
        )
        async with self._session_factory() as session, session.begin():
            if (await session.execute(insert)).first() is not None:
                return "new"
            status = (
                await session.execute(
                    select(InboundMessageModel.status).where(
                        InboundMessageModel.message_id == event.message_id
                    )
                )
            ).scalar_one()
        return "done" if status == "done" else "retry"

    async def complete(
        self, message_id: str, reply: OutboundMessageReady | None, *, at: datetime
    ) -> None:
        """Marca `done` e grava o outbox na MESMA transação (falha em um desfaz o outro)."""
        reply_json = reply.model_dump_json() if reply is not None else None
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(InboundMessageModel)
                .where(InboundMessageModel.message_id == message_id)
                .values(status="done", reply_json=reply_json, updated_at=at)
            )
            if reply is not None:
                session.add(
                    OutboxModel(
                        topic=TOPIC_OUTBOUND,
                        key=reply.conversation_id,
                        payload_json=reply_json,
                        inbound_message_id=message_id,
                        created_at=at,
                        traceparent=current_traceparent(),
                    )
                )
