"""Registro de idempotência em Postgres (ADR 0011)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.models import IdempotencyRecordModel


class SqlIdempotencyRegistry:
    """Implementa ``IdempotencyRegistry``; nunca sobrescreve um fingerprint diferente."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> tuple[str, str] | None:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(
                        IdempotencyRecordModel.fingerprint, IdempotencyRecordModel.result_json
                    ).where(IdempotencyRecordModel.key == key)
                )
            ).first()
            return (row.fingerprint, row.result_json) if row is not None else None

    async def put(self, key: str, fingerprint: str, result_json: str) -> None:
        insert = pg_insert(IdempotencyRecordModel).values(
            key=key, fingerprint=fingerprint, result_json=result_json
        )
        statement = insert.on_conflict_do_update(
            index_elements=[IdempotencyRecordModel.key],
            set_={"result_json": insert.excluded.result_json, "updated_at": func.now()},
            where=IdempotencyRecordModel.fingerprint == insert.excluded.fingerprint,
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def purge(self, older_than: datetime) -> int:
        """Apaga registros criados antes do corte; devolve quantos saíram."""
        statement = (
            delete(IdempotencyRecordModel)
            .where(IdempotencyRecordModel.created_at < older_than)
            .returning(IdempotencyRecordModel.key)
        )
        async with self._session_factory() as session, session.begin():
            return len((await session.execute(statement)).all())
