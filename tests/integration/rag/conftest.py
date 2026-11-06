"""Fixtures de Postgres para os testes de RAG (mesmo padrão da persistência)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from commerce_agents.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
)
from commerce_agents.infrastructure.persistence.migrate import upgrade_to_head
from tests.integration.persistence.conftest import (  # noqa: F401
    migration_sync_url,
    postgres_container,
)


@pytest_asyncio.fixture
async def rag_db(
    migration_sync_url: str,  # noqa: F811 - fixture importada do conftest de persistência
) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    """Banco novo migrado até head (inclui a migration 0004 de policy_chunks)."""
    upgrade_to_head(migration_sync_url)
    engine = create_engine(migration_sync_url.replace("+psycopg", "+asyncpg"))
    try:
        yield engine, create_session_factory(engine)
    finally:
        await engine.dispose()
