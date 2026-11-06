"""Constraints do schema aplicadas pelo Postgres."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.models import (
    ConversationModel,
    CustomerModel,
    MessageModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    VariantModel,
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


def _valid_order_model(order_id: str = "O000001", *, total_cents: int = 1000) -> OrderModel:
    return OrderModel(
        order_id=order_id,
        customer_id="C0001",
        status="pending_payment",
        created_at=BASE_TIME,
        delivered_at=None,
        tracking_code=None,
        total_cents=total_cents,
        carrier="Correios",
        cep="01000-000",
        method="standard",
    )


def _valid_product_model(product_id: str = "P0001", *, price_cents: int = 1000) -> ProductModel:
    return ProductModel(
        product_id=product_id,
        name="Tênis Urban Run",
        brand="Voltz",
        category="calcados",
        price_cents=price_cents,
        description="Tênis de corrida urbano.",
    )


async def test_negative_order_total_violates_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_customer(session)
        session.add(_valid_order_model(total_cents=-1))

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_negative_order_item_unit_price_violates_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_customer(session)
        session.add(_valid_order_model())
        await session.commit()

        session.add(
            OrderItemModel(
                order_id="O000001",
                position=0,
                sku="SKU-1",
                qty=1,
                unit_price_cents=-1,
            )
        )

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_order_item_qty_below_one_violates_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_customer(session)
        session.add(_valid_order_model())
        await session.commit()

        session.add(
            OrderItemModel(
                order_id="O000001",
                position=0,
                sku="SKU-1",
                qty=0,
                unit_price_cents=1000,
            )
        )

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_negative_variant_stock_violates_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(_valid_product_model())
        await session.commit()

        session.add(
            VariantModel(
                sku="SKU-1",
                product_id="P0001",
                size="42",
                color="preto",
                stock=-1,
            )
        )

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_negative_product_price_violates_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(_valid_product_model(price_cents=-1))

        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_zero_and_minimum_values_are_accepted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_customer(session)
        session.add(_valid_order_model(total_cents=0))
        session.add(_valid_product_model(price_cents=0))
        await session.commit()

        session.add(
            VariantModel(
                sku="SKU-1",
                product_id="P0001",
                size="42",
                color="preto",
                stock=0,
            )
        )
        session.add(
            OrderItemModel(
                order_id="O000001",
                position=0,
                sku="SKU-1",
                qty=1,
                unit_price_cents=0,
            )
        )
        await session.commit()

        assert await session.get(OrderModel, "O000001") is not None
        assert await session.get(ProductModel, "P0001") is not None
        assert await session.get(VariantModel, "SKU-1") is not None
        assert await session.get(OrderItemModel, ("O000001", 0)) is not None
