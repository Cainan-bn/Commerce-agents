"""Carga idempotente de data/seed (jsonl) no PostgreSQL via upsert por chave primária.

Rodar duas vezes não duplica linhas nem falha: cada lote é um INSERT ... ON CONFLICT
DO UPDATE sobre a chave primária da tabela. Toda a carga roda em uma única transação.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.schema import Table

from commerce_agents.infrastructure.persistence.migrate import sync_url_from_env
from commerce_agents.infrastructure.persistence.models import (
    CustomerModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    ReturnRequestModel,
    VariantModel,
)

DEFAULT_DATA_DIR = Path("data/seed")
DEFAULT_BATCH_SIZE = 500

# Tabelas carregadas, na ordem de dependência das FKs.
_LOADED_MODELS = (
    CustomerModel,
    ProductModel,
    VariantModel,
    OrderModel,
    OrderItemModel,
    ReturnRequestModel,
)


def async_url_from_env() -> str:
    """Deriva a URL assíncrona (asyncpg) com a mesma regra do alvo ``migrate``."""
    return sync_url_from_env().replace("+psycopg", "+asyncpg")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _parse_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _customer_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "customer_id": record["customer_id"],
            "name": record["name"],
            "email": record["email"],
            "phone": record["phone"],
            "created_at": _parse_datetime(record["created_at"]),
        }
        for record in records
    ]


def _product_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "product_id": record["product_id"],
            "name": record["name"],
            "brand": record["brand"],
            "category": record["category"],
            "price_cents": record["price_cents"],
            "description": record["description"],
        }
        for record in records
    ]


def _variant_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sku": variant["sku"],
            "product_id": record["product_id"],
            "size": variant["size"],
            "color": variant["color"],
            "stock": variant["stock"],
        }
        for record in records
        for variant in record["variants"]
    ]


def _order_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order_id": record["order_id"],
            "customer_id": record["customer_id"],
            "status": record["status"],
            "created_at": _parse_datetime(record["created_at"]),
            "delivered_at": _parse_datetime(record["delivered_at"]),
            "tracking_code": record["tracking_code"],
            "total_cents": record["total_cents"],
            "carrier": record["shipping"]["carrier"],
            "cep": record["shipping"]["cep"],
            "method": record["shipping"]["method"],
        }
        for record in records
    ]


def _order_item_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order_id": record["order_id"],
            "position": position,
            "sku": item["sku"],
            "qty": item["qty"],
            "unit_price_cents": item["unit_price_cents"],
        }
        for record in records
        for position, item in enumerate(record["items"])
    ]


def _return_request_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order_id": record["order_id"],
            "sku": record["return_request"]["sku"],
            "reason": record["return_request"]["reason"],
            "requested_at": _parse_datetime(record["return_request"]["requested_at"]),
        }
        for record in records
        if record["return_request"] is not None
    ]


def build_rows(data_dir: Path) -> dict[type, list[dict[str, Any]]]:
    """Converte os jsonl do seed nas linhas de cada tabela, na ordem de ``_LOADED_MODELS``."""
    products = _read_jsonl(data_dir / "products.jsonl")
    customers = _read_jsonl(data_dir / "customers.jsonl")
    orders = _read_jsonl(data_dir / "orders.jsonl")
    return {
        CustomerModel: _customer_rows(customers),
        ProductModel: _product_rows(products),
        VariantModel: _variant_rows(products),
        OrderModel: _order_rows(orders),
        OrderItemModel: _order_item_rows(orders),
        ReturnRequestModel: _return_request_rows(orders),
    }


def _chunks(rows: Sequence[dict[str, Any]], size: int) -> Iterable[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def _upsert(
    connection: AsyncConnection,
    table: Table,
    rows: Sequence[dict[str, Any]],
    batch_size: int,
) -> None:
    primary_key = [column.name for column in table.primary_key.columns]
    updatable = [name for name in rows[0] if name not in primary_key] if rows else []
    for batch in _chunks(rows, batch_size):
        statement = insert(table).values(list(batch))
        if updatable:
            statement = statement.on_conflict_do_update(
                index_elements=primary_key,
                set_={name: statement.excluded[name] for name in updatable},
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=primary_key)
        await connection.execute(statement)


async def load_seed(database_url: str, data_dir: Path, batch_size: int) -> dict[str, int]:
    """Carrega o seed e devolve a contagem final de cada tabela carregada."""
    rows_by_model = build_rows(data_dir)
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for model in _LOADED_MODELS:
                await _upsert(connection, model.__table__, rows_by_model[model], batch_size)
            counts: dict[str, int] = {}
            for model in _LOADED_MODELS:
                result = await connection.execute(select(func.count()).select_from(model))
                counts[model.__tablename__] = int(result.scalar_one())
    finally:
        await engine.dispose()
    return counts


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    counts = asyncio.run(load_seed(async_url_from_env(), args.data_dir, args.batch_size))
    print(f"[seed-db] carga concluida em {args.data_dir}")
    for table, count in counts.items():
        print(f"  {table:<16} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
