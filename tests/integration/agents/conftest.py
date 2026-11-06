"""Fixtures do checkpointer Postgres do grafo: banco novo por teste (padrão da persistência)."""

from tests.integration.persistence.conftest import (  # noqa: F401
    migration_sync_url,
    postgres_container,
)
