"""Carga idempotente de data/seed no Postgres real via scripts/load_seed.py."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from commerce_agents.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
)
from commerce_agents.infrastructure.persistence.migrate import upgrade_to_head
from commerce_agents.infrastructure.persistence.models import (
    CustomerModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    ReturnRequestModel,
    VariantModel,
)
from tests.integration.persistence.conftest import PostgresConnection

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "data" / "seed"
LOAD_SCRIPT = REPO_ROOT / "scripts" / "load_seed.py"


def _read_jsonl(name: str) -> list[dict[str, Any]]:
    lines = (SEED_DIR / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _run_load(async_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = async_url
    return subprocess.run(
        [sys.executable, str(LOAD_SCRIPT), "--data-dir", str(SEED_DIR)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@pytest.fixture(scope="module")
def seeded_async_url(postgres_container: PostgresConnection) -> str:
    """Migra um banco novo e executa a carga do seed duas vezes."""
    name = f"seed_db_{secrets.token_hex(4)}"
    with psycopg.connect(postgres_container.admin_dsn, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    sync_url = (
        f"postgresql+psycopg://{postgres_container.user}:{postgres_container.password}"
        f"@{postgres_container.host}:{postgres_container.port}/{name}"
    )
    upgrade_to_head(sync_url)
    async_url = sync_url.replace("+psycopg", "+asyncpg")

    first = _run_load(async_url)
    assert first.returncode == 0, first.stderr
    second = _run_load(async_url)
    assert second.returncode == 0, second.stderr
    return async_url


@pytest_asyncio.fixture
async def loaded_engine(seeded_async_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(seeded_async_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _count(session: AsyncSession, model: type) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def test_second_load_keeps_expected_counts(loaded_engine: AsyncEngine) -> None:
    products = _read_jsonl("products.jsonl")
    customers = _read_jsonl("customers.jsonl")
    orders = _read_jsonl("orders.jsonl")
    variants_total = sum(len(product["variants"]) for product in products)
    items_total = sum(len(order["items"]) for order in orders)
    returns_total = sum(1 for order in orders if order["return_request"] is not None)

    factory = create_session_factory(loaded_engine)
    async with factory() as session:
        assert await _count(session, CustomerModel) == len(customers)
        assert await _count(session, ProductModel) == len(products)
        assert await _count(session, VariantModel) == variants_total
        assert await _count(session, OrderModel) == len(orders)
        assert await _count(session, OrderItemModel) == items_total
        assert await _count(session, ReturnRequestModel) == returns_total


async def test_seed_has_no_duplicates_or_broken_foreign_keys(loaded_engine: AsyncEngine) -> None:
    async with loaded_engine.connect() as connection:
        duplicated_orders = await connection.execute(
            text(
                "SELECT count(*) FROM (SELECT order_id FROM orders "
                "GROUP BY order_id HAVING count(*) > 1) d"
            )
        )
        assert duplicated_orders.scalar_one() == 0

        orphan_orders = await connection.execute(
            text(
                "SELECT count(*) FROM orders o "
                "LEFT JOIN customers c ON c.customer_id = o.customer_id "
                "WHERE c.customer_id IS NULL"
            )
        )
        assert orphan_orders.scalar_one() == 0

        orphan_variants = await connection.execute(
            text(
                "SELECT count(*) FROM product_variants v "
                "LEFT JOIN products p ON p.product_id = v.product_id "
                "WHERE p.product_id IS NULL"
            )
        )
        assert orphan_variants.scalar_one() == 0


async def test_delivered_order_keeps_delivery_and_shipping_after_reload(
    loaded_engine: AsyncEngine,
) -> None:
    order_seed = next(
        order for order in _read_jsonl("orders.jsonl") if order["status"] == "delivered"
    )
    expected_delivered_at = datetime.fromisoformat(
        order_seed["delivered_at"].replace("Z", "+00:00")
    )

    factory = create_session_factory(loaded_engine)
    async with factory() as session:
        order = await session.get(OrderModel, order_seed["order_id"])

    assert order is not None
    assert order.status == "delivered"
    assert order.delivered_at == expected_delivered_at
    assert order.carrier == order_seed["shipping"]["carrier"]
    assert order.carrier != ""
    assert order.cep == order_seed["shipping"]["cep"]
    assert order.method == order_seed["shipping"]["method"]
