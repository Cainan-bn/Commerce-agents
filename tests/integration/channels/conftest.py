"""Fixtures de Postgres e Redpanda para os testes de canais (padrão da persistência)."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
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
async def channels_db(
    migration_sync_url: str,  # noqa: F811 - fixture importada do conftest de persistência
) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    """Banco novo migrado até head (inclui 0006: inbound_messages, outbox, handoffs)."""
    upgrade_to_head(migration_sync_url)
    engine = create_engine(migration_sync_url.replace("+psycopg", "+asyncpg"))
    try:
        yield engine, create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def redpanda_bootstrap() -> Iterator[str]:
    """Redpanda via GenericContainer (testcontainers 4.15 não traz RedpandaContainer).

    Se a imagem não subir, o teste é marcado como skip com motivo explícito.
    """
    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs
    except ImportError as error:  # pragma: no cover - ambiente sem testcontainers
        pytest.skip(f"testcontainers indisponível: {error}")
    container: Any = (
        DockerContainer("docker.redpanda.com/redpandadata/redpanda:v24.2.4")
        .with_command(
            "redpanda start --overprovisioned --smp 1 --memory 1G "
            "--kafka-addr PLAINTEXT://0.0.0.0:9092 "
            "--advertise-kafka-addr PLAINTEXT://127.0.0.1:9092"
        )
        .with_bind_ports(9092, 9092)
    )
    try:
        container.start()
        wait_for_logs(container, "Successfully started Redpanda", timeout=120)
    except Exception as error:  # noqa: BLE001 - qualquer falha de subir o broker vira skip
        pytest.skip(f"Redpanda não subiu: {error}")
    try:
        yield "127.0.0.1:9092"
    finally:
        container.stop()
