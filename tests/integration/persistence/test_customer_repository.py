"""Contrato do SqlCustomerRepository contra Postgres real."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.repositories import SqlCustomerRepository
from tests.unit.domain.builders import make_customer

pytestmark = pytest.mark.integration


async def test_save_and_get_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlCustomerRepository(session_factory)
    customer = make_customer()

    await repository.save(customer)

    assert await repository.get(customer.customer_id) == customer


async def test_save_is_upsert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlCustomerRepository(session_factory)
    customer = make_customer()
    updated = make_customer(customer_id=customer.customer_id, name="Nome Atualizado")

    await repository.save(customer)
    await repository.save(updated)

    assert await repository.get(customer.customer_id) == updated


async def test_get_missing_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlCustomerRepository(session_factory)

    assert await repository.get("C999999") is None
