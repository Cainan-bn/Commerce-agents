"""Fixtures de Postgres real via testcontainers para os testes de persistência."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from commerce_agents.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
)
from commerce_agents.infrastructure.persistence.migrate import upgrade_to_head

TEST_TABLES = (
    "messages",
    "conversations",
    "return_requests",
    "order_items",
    "orders",
    "product_variants",
    "products",
    "customers",
)


@dataclass(frozen=True)
class PostgresConnection:
    """URLs e credenciais geradas para o container de teste."""

    async_url: str
    sync_url: str
    host: str
    port: int
    user: str
    password: str
    dbname: str

    @property
    def admin_dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}" f"@{self.host}:{self.port}/{self.dbname}"


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresConnection]:
    suffix = secrets.token_hex(4)
    user = f"test_user_{suffix}"
    password = secrets.token_urlsafe(18)
    dbname = f"test_db_{suffix}"

    container = PostgresContainer(
        "pgvector/pgvector:pg16",
        username=user,
        password=password,
        dbname=dbname,
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(5432))
        connection = PostgresConnection(
            async_url=f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}",
            sync_url=f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}",
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
        )
        upgrade_to_head(connection.sync_url)
        yield connection
    finally:
        container.stop()


@pytest_asyncio.fixture
async def session_factory(
    postgres_container: PostgresConnection,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(postgres_container.async_url)
    factory = create_session_factory(engine)
    tables = ", ".join(TEST_TABLES)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def migration_sync_url(
    postgres_container: PostgresConnection,
) -> Iterator[str]:
    name = f"migration_db_{secrets.token_hex(4)}"
    with psycopg.connect(postgres_container.admin_dsn, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')

    url = (
        f"postgresql+psycopg://{postgres_container.user}:{postgres_container.password}"
        f"@{postgres_container.host}:{postgres_container.port}/{name}"
    )
    try:
        yield url
    finally:
        with psycopg.connect(postgres_container.admin_dsn, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest_asyncio.fixture
async def engine_and_factory(
    migration_sync_url: str,
) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    """Banco novo migrado até head, para os testes de confirmação e idempotência."""
    upgrade_to_head(migration_sync_url)
    engine = create_engine(migration_sync_url.replace("+psycopg", "+asyncpg"))
    try:
        yield engine, create_session_factory(engine)
    finally:
        await engine.dispose()
