"""Memória de longo prazo do cliente em Postgres (implementa `CustomerMemory`)."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.models import CustomerPreferenceModel


class SqlCustomerMemory:
    """Preferências por cliente. Nesta fase o grafo só lê; `set_preference` é upsert."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_preferences(self, customer_id: str) -> dict[str, str]:
        statement = select(CustomerPreferenceModel.key, CustomerPreferenceModel.value).where(
            CustomerPreferenceModel.customer_id == customer_id
        )
        async with self._session_factory() as session, session.begin():
            rows = (await session.execute(statement)).all()
        return {row.key: row.value for row in rows}

    async def set_preference(self, customer_id: str, key: str, value: str) -> None:
        insert = pg_insert(CustomerPreferenceModel).values(
            customer_id=customer_id, key=key, value=value
        )
        statement = insert.on_conflict_do_update(
            index_elements=[CustomerPreferenceModel.customer_id, CustomerPreferenceModel.key],
            set_={"value": insert.excluded.value, "updated_at": func.now()},
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)
