"""Contrato do SqlOrderRepository contra Postgres real."""

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.domain.order.status import OrderStatus
from commerce_agents.infrastructure.persistence.repositories import (
    SqlCustomerRepository,
    SqlOrderRepository,
)
from tests.unit.domain.builders import BASE_TIME, make_customer, make_item, make_order

pytestmark = pytest.mark.integration


async def _prepare(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[SqlOrderRepository, str]:
    customers = SqlCustomerRepository(session_factory)
    await customers.save(make_customer(customer_id="C0001"))
    return SqlOrderRepository(session_factory), "C0001"


async def test_save_and_find_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository, _ = await _prepare(session_factory)
    order = make_order(
        status=OrderStatus.delivered,
        items=(
            make_item(sku="SKU-A", qty=1, unit_price_cents=1000),
            make_item(sku="SKU-B", qty=2, unit_price_cents=550),
        ),
    )

    await repository.save(order)

    assert await repository.find(order.order_id) == order


async def test_save_existing_updates_status_without_duplicating_items(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository, customer_id = await _prepare(session_factory)
    order = make_order(customer_id=customer_id)
    updated = make_order(
        order_id=order.order_id,
        customer_id=customer_id,
        status=OrderStatus.processing,
        items=order.items,
        created_at=order.created_at,
    )

    await repository.save(order)
    await repository.save(updated)

    assert await repository.find(order.order_id) == updated
    async with session_factory() as session:
        total = await session.scalar(
            text("SELECT count(*) FROM order_items WHERE order_id = :order_id"),
            {"order_id": order.order_id},
        )
    assert total == len(order.items)


async def test_find_missing_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository, _ = await _prepare(session_factory)

    assert await repository.find("O999999") is None


async def test_get_returns_order_view(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository, customer_id = await _prepare(session_factory)
    order = make_order(customer_id=customer_id, status=OrderStatus.in_transit)
    await repository.save(order)

    view = await repository.get(order.order_id)

    assert view is not None
    assert view.order_id == order.order_id
    assert view.customer_id == customer_id
    assert view.status == OrderStatus.in_transit.value
    assert view.tracking_code == order.tracking_code
    assert view.created_at == order.created_at
    assert view.delivered_at is None
    assert view.total_cents == order.total_cents


async def test_list_by_customer_is_sorted_and_isolated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customers = SqlCustomerRepository(session_factory)
    await customers.save(make_customer(customer_id="C0001"))
    await customers.save(make_customer(customer_id="C0002"))
    repository = SqlOrderRepository(session_factory)

    older = make_order(
        order_id="O000001",
        customer_id="C0001",
        created_at=BASE_TIME,
    )
    newer = make_order(
        order_id="O000002",
        customer_id="C0001",
        created_at=BASE_TIME + timedelta(days=2),
    )
    other = make_order(
        order_id="O000003",
        customer_id="C0002",
        created_at=BASE_TIME + timedelta(days=1),
    )
    for order in (older, newer, other):
        await repository.save(order)

    views = await repository.list_by_customer("C0001")

    assert [view.order_id for view in views] == ["O000002", "O000001"]
    assert all(view.customer_id == "C0001" for view in views)
