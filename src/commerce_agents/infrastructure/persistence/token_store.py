"""Token de confirmação em Postgres: sha256 no banco e consumo atômico (ADR 0008 e 0011)."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.models import ConfirmationTokenModel


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SqlConfirmationTokenStore:
    """Implementa ``ConfirmationTokenStore`` compartilhável entre processos."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Callable[[], datetime]
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def issue(
        self, conversation_id: str, action: str, arguments_digest: str, ttl_seconds: int
    ) -> str:
        token = secrets.token_urlsafe(24)
        async with self._session_factory() as session, session.begin():
            session.add(
                ConfirmationTokenModel(
                    token_hash=_hash(token),
                    conversation_id=conversation_id,
                    action=action,
                    arguments_digest=arguments_digest,
                    expires_at=self._clock() + timedelta(seconds=ttl_seconds),
                )
            )
        return token

    async def consume(
        self, token: str, conversation_id: str, action: str, arguments_digest: str
    ) -> bool:
        now = self._clock()
        statement = (
            update(ConfirmationTokenModel)
            .where(
                ConfirmationTokenModel.token_hash == _hash(token),
                ConfirmationTokenModel.used_at.is_(None),
                ConfirmationTokenModel.expires_at > now,
                ConfirmationTokenModel.conversation_id == conversation_id,
                ConfirmationTokenModel.action == action,
                ConfirmationTokenModel.arguments_digest == arguments_digest,
            )
            .values(used_at=now)
            .returning(ConfirmationTokenModel.token_hash)
        )
        async with self._session_factory() as session, session.begin():
            return (await session.execute(statement)).first() is not None

    async def purge(self, older_than: datetime) -> int:
        """Apaga tokens usados ou expirados antes do corte; um token ainda válido nunca sai."""
        expired_before = min(older_than, self._clock())
        statement = (
            delete(ConfirmationTokenModel)
            .where(
                or_(
                    ConfirmationTokenModel.used_at < older_than,
                    ConfirmationTokenModel.expires_at < expired_before,
                )
            )
            .returning(ConfirmationTokenModel.token_hash)
        )
        async with self._session_factory() as session, session.begin():
            return len((await session.execute(statement)).all())
