"""Orquestra a geração determinística dos arquivos de seed."""

from __future__ import annotations

import json
import random
from pathlib import Path

from data.generators.catalog import generate_products
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
    _write_jsonl(
        out_dir / "products.jsonl", [product.model_dump(mode="json") for product in products]
    )

    return validate_files(out_dir)
