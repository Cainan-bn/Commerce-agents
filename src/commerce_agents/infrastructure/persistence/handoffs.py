"""Repositório de handoffs em Postgres (ADR 0014)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.application.dto.channels import HandoffMessage, HandoffRecord
from commerce_agents.infrastructure.persistence.models import HandoffMessageModel, HandoffModel


def _record(row: HandoffModel) -> HandoffRecord:
    return HandoffRecord.model_validate(
        {
            "handoff_id": row.handoff_id,
            "conversation_id": row.conversation_id,
            "status": row.status,
            "reason": row.reason,
            "priority": row.priority,
            "summary": row.summary,
            "created_at": row.created_at,
            "claimed_by": row.claimed_by,
            "closed_at": row.closed_at,
        },
        strict=False,
    )


class SqlHandoffRepository:
    """Implementa `HandoffRepository`; `claim` e `close` são atômicos por UPDATE condicional."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, record: HandoffRecord) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                HandoffModel(
                    handoff_id=record.handoff_id,
                    conversation_id=record.conversation_id,
                    status=record.status.value,
                    reason=record.reason,
                    priority=record.priority,
                    summary=record.summary,
                    created_at=record.created_at,
                    claimed_by=record.claimed_by,
                    closed_at=record.closed_at,
                )
            )

    async def get(self, handoff_id: str) -> HandoffRecord | None:
        return await self._one(HandoffModel.handoff_id == handoff_id)

    async def get_active(self, conversation_id: str) -> HandoffRecord | None:
        return await self._one(
            HandoffModel.conversation_id == conversation_id, HandoffModel.status != "closed"
        )

    async def list_active(self) -> Sequence[HandoffRecord]:
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.execute(
                    select(HandoffModel)
                    .where(HandoffModel.status != "closed")
                    .order_by(HandoffModel.created_at)
                )
            ).scalars()
            return [_record(row) for row in rows]

    async def claim(self, handoff_id: str, agent: str, *, at: datetime) -> HandoffRecord | None:
        return await self._update(
            handoff_id, HandoffModel.status == "open", status="claimed", claimed_by=agent
        )

    async def close(self, handoff_id: str, *, at: datetime) -> HandoffRecord | None:
        return await self._update(
            handoff_id, HandoffModel.status != "closed", status="closed", closed_at=at
        )

    async def add_message(self, message: HandoffMessage) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                HandoffMessageModel(
                    handoff_id=message.handoff_id,
                    author=message.author,
                    text=message.text,
                    sent_at=message.sent_at,
                )
            )

    async def messages(self, handoff_id: str) -> Sequence[HandoffMessage]:
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.execute(
                    select(HandoffMessageModel)
                    .where(HandoffMessageModel.handoff_id == handoff_id)
                    .order_by(HandoffMessageModel.id)
                )
            ).scalars()
            return [
                HandoffMessage.model_validate(
                    {
                        "handoff_id": row.handoff_id,
                        "author": row.author,
                        "text": row.text,
                        "sent_at": row.sent_at,
                    }
                )
                for row in rows
            ]

    async def _one(self, *conditions: Any) -> HandoffRecord | None:
        async with self._session_factory() as session, session.begin():
            row = (await session.execute(select(HandoffModel).where(*conditions))).scalars().first()
            return _record(row) if row is not None else None

    async def _update(self, handoff_id: str, condition: Any, **values: Any) -> HandoffRecord | None:
        statement = (
            update(HandoffModel)
            .where(HandoffModel.handoff_id == handoff_id, condition)
            .values(**values)
            .returning(HandoffModel)
        )
        async with self._session_factory() as session, session.begin():
            row = (await session.execute(statement)).scalars().first()
            return _record(row) if row is not None else None
