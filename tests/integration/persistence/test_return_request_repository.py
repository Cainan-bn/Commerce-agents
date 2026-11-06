"""Contrato do SqlReturnRequestRepository contra Postgres real."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.repositories import (
    SqlCustomerRepository,
    SqlOrderRepository,
    SqlReturnRequestRepository,
)
from tests.unit.domain.builders import (
    BASE_TIME,
    make_customer,
    make_order,
    make_return_request,
)

pytestmark = pytest.mark.integration


async def _prepare_orders(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customers = SqlCustomerRepository(session_factory)
    await customers.save(make_customer(customer_id="C0001"))
    orders = SqlOrderRepository(session_factory)
    await orders.save(make_order(order_id="O000001", customer_id="C0001"))
    await orders.save(make_order(order_id="O000002", customer_id="C0001"))


async def test_add_is_idempotent_for_same_order_and_sku(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _prepare_orders(session_factory)
    repository = SqlReturnRequestRepository(session_factory)
    request = make_return_request(order_id="O000001", sku="SKU-1")

    await repository.add(request)
    await repository.add(request)

    assert await repository.list_for_order("O000001") == (request,)


async def test_list_for_order_is_ordered_and_isolated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _prepare_orders(session_factory)
    repository = SqlReturnRequestRepository(session_factory)
    later = make_return_request(
        order_id="O000001",
        sku="SKU-2",
        requested_at=BASE_TIME + timedelta(days=1),
    )
    earlier = make_return_request(
        order_id="O000001",
        sku="SKU-1",
        requested_at=BASE_TIME,
    )
    other_order = make_return_request(order_id="O000002", sku="SKU-1")

    await repository.add(later)
    await repository.add(earlier)
    await repository.add(other_order)

    assert await repository.list_for_order("O000001") == (earlier, later)
    assert await repository.list_for_order("O000002") == (other_order,)
