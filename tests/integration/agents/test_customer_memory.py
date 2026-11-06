"""SqlCustomerMemory contra Postgres real (migration 0005)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.agents.memory import SqlCustomerMemory
from commerce_agents.infrastructure.persistence.repositories import SqlCustomerRepository
from tests.integration.persistence.conftest import session_factory  # noqa: F401
from tests.unit.domain.builders import make_customer

pytestmark = pytest.mark.integration


async def _memory(factory: async_sessionmaker[AsyncSession]) -> SqlCustomerMemory:
    await SqlCustomerRepository(factory).save(make_customer(customer_id="C0001"))
    return SqlCustomerMemory(factory)


async def test_cliente_sem_preferencias_devolve_vazio(
    session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
):
    memory = await _memory(session_factory)

    assert await memory.get_preferences("C0001") == {}


async def test_set_e_get_com_upsert(session_factory: async_sessionmaker[AsyncSession]):  # noqa: F811
    memory = await _memory(session_factory)

    await memory.set_preference("C0001", "tamanho", "M")
    await memory.set_preference("C0001", "cor", "azul")
    await memory.set_preference("C0001", "tamanho", "G")

    assert await memory.get_preferences("C0001") == {"tamanho": "G", "cor": "azul"}
