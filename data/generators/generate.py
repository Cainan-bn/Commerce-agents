"""Orquestra a geração determinística dos arquivos de seed."""

from __future__ import annotations

import json
import random
from pathlib import Path

from data.generators.catalog import generate_products
from data.generators.customers import generate_customers
from data.generators.orders import generate_orders, redate_recent_deliveries
from data.generators.validation import validate_files

DEFAULT_SEED = 42
DEFAULT_OUT = Path("data/seed")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def generate(seed: int, out_dir: Path) -> dict[str, int]:
    """Gera os arquivos do seed e revalida cada linha produzida."""
    out_dir.mkdir(parents=True, exist_ok=True)

    products = generate_products(random.Random(seed))
    customers = generate_customers(random.Random(seed + 1))
    orders = generate_orders(random.Random(seed + 2), products, customers)
    orders = redate_recent_deliveries(orders, seed)

    _write_jsonl(
        out_dir / "products.jsonl", [product.model_dump(mode="json") for product in products]
    )
    _write_jsonl(
        out_dir / "customers.jsonl", [customer.model_dump(mode="json") for customer in customers]
    )
    _write_jsonl(out_dir / "orders.jsonl", [order.model_dump(mode="json") for order in orders])

    return validate_files(out_dir)
