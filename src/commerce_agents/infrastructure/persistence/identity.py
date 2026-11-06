"""Resolução de identidade do canal para cliente da loja (ADR 0014)."""

import re

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.persistence.models import CustomerModel

_COUNTRY_CODE = "55"


class SqlIdentityResolver:
    """WhatsApp: telefone por dígitos. Web: `external_id` é o `customer_id` da sessão assinada.
    Instagram: sem vínculo com a loja (anônimo)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def resolve(self, channel: Channel, external_id: str) -> str | None:
        if channel is Channel.WEB:
            return await self._first(CustomerModel.customer_id == external_id)
        if channel is Channel.WHATSAPP:
            digits = re.sub(r"\D", "", external_id)
            if not digits:
                return None
            candidates = {digits, _COUNTRY_CODE + digits}
            phone_digits = func.regexp_replace(CustomerModel.phone, r"\D", "", "g")
            return await self._first(phone_digits.in_(candidates))
        return None

    async def _first(self, condition: ColumnElement[bool]) -> str | None:
        async with self._session_factory() as session, session.begin():
            ids = (
                (await session.execute(select(CustomerModel.customer_id).where(condition).limit(2)))
                .scalars()
                .all()
            )
        return ids[0] if len(ids) == 1 else None  # ambíguo vira anônimo
