"""Constraints do schema aplicadas pelo Postgres."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.models import (
    ConversationModel,
    CustomerModel,
    MessageModel,
    OrderModel,
)
from tests.unit.domain.builders import BASE_TIME

pytestmark = pytest.mark.integration


async def _insert_customer(session: AsyncSession) -> None:
    session.add(
        CustomerModel(
            customer_id="C0001",
            name="Maria Fictícia",
            email="maria@example.com",
            phone="+5511 90000-0001",
            created_at=BASE_TIME,
        )
    )
    await session.commit()


async def test_invalid_order_status_violates_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_customer(session)
        session.add(
            OrderModel(
                order_id="O000001",
                customer_id="C0001",
                status="status-invalido",
                created_at=BASE_TIME,
                delivered_at=None,
                tracking_code=None,
                total_cents=1000,
                carrier="Correios",
                cep="01000-000",
                method="standard",
            )
        )

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_duplicate_message_id_violates_unique_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                ConversationModel(
                    conversation_id="CONV-A",
                    status="open",
                    created_at=BASE_TIME,
                ),
                ConversationModel(
                    conversation_id="CONV-B",
                    status="open",
                    created_at=BASE_TIME,
                ),
            ]
        )
        await session.commit()

        session.add(
            MessageModel(
                message_id="MSG-1",
                conversation_id="CONV-A",
                position=0,
                text="oi",
                sent_at=BASE_TIME,
            )
        )
        await session.commit()

        session.add(
            MessageModel(
                message_id="MSG-1",
                conversation_id="CONV-B",
                position=0,
                text="duplicada",
                sent_at=BASE_TIME,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
