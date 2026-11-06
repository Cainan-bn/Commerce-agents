"""Ciclo completo de migrations Alembic em banco limpo."""

import pytest
from sqlalchemy import create_engine, inspect

from commerce_agents.infrastructure.persistence.migrate import (
    downgrade_to_base,
    upgrade_to_head,
)

pytestmark = pytest.mark.integration


def test_upgrade_downgrade_upgrade_from_clean_database(migration_sync_url: str) -> None:
    upgrade_to_head(migration_sync_url)
    engine = create_engine(migration_sync_url)
    try:
        assert inspect(engine).has_table("orders")
        assert inspect(engine).has_table("messages")

        downgrade_to_base(migration_sync_url)
        assert not inspect(engine).has_table("orders")

        upgrade_to_head(migration_sync_url)
        assert inspect(engine).has_table("orders")
    finally:
        engine.dispose()
