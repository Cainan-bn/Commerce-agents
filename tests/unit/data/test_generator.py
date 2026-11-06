"""Testes de contrato, coerência e determinismo do gerador de seed."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from data.generators.generate import generate
from data.generators.models import Order, OrderItem, Product, ShippingInfo
from data.generators.validation import SeedValidationError, check_order, validate_files
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
TODAY = datetime(2026, 11, 1, tzinfo=UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _generate(tmp_path: Path, seed: int = 42) -> Path:
    out = tmp_path / "seed"
    generate(seed, out)
    return out


def _run_cli(out: Path, seed: int = 42) -> None:
    subprocess.run(
        [sys.executable, "-m", "data.generators", "--seed", str(seed), "--out", str(out)],
        check=True,
        cwd=REPO_ROOT,
    )


def _order(**overrides: object) -> Order:
    base: dict[str, object] = {
        "order_id": "O000001",
        "customer_id": "C0001",
        "status": "paid",
        "created_at": datetime(2026, 10, 20, tzinfo=UTC),
        "delivered_at": None,
        "tracking_code": None,
        "total_cents": 100,
        "items": [OrderItem(sku="P0001-42-PRETO", qty=1, unit_price_cents=100)],
        "shipping": ShippingInfo(carrier="Correios", cep="01000-000", method="standard"),
    }
    base.update(overrides)
    return Order(**base)


@pytest.mark.unit
def test_generator_is_deterministic(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _run_cli(dir_a)
    _run_cli(dir_b)

    for name in ("products.jsonl", "customers.jsonl", "orders.jsonl"):
        assert _sha256(dir_a / name) == _sha256(dir_b / name)


@pytest.mark.unit
def test_seed_counts(tmp_path: Path) -> None:
    out = _generate(tmp_path)

    assert len(_load_jsonl(out / "products.jsonl")) >= 290
    assert len(_load_jsonl(out / "customers.jsonl")) >= 190
    assert len(_load_jsonl(out / "orders.jsonl")) >= 990


@pytest.mark.unit
def test_status_distribution_within_tolerance(tmp_path: Path) -> None:
    orders = _load_jsonl(_generate(tmp_path) / "orders.jsonl")
    total = len(orders)
    counts: dict[str, int] = {}
    for order in orders:
        status = str(order["status"])
        counts[status] = counts.get(status, 0) + 1

    target = {
        "delivered": 45,
        "in_transit": 12,
        "shipped": 8,
        "processing": 8,
        "paid": 6,
        "pending_payment": 5,
        "cancelled": 8,
        "return_requested": 4,
        "returned": 4,
    }
    for status, expected in target.items():
        actual = counts.get(status, 0) / total * 100
        assert abs(actual - expected) <= 3.0, f"{status}: {actual:.2f}% vs {expected}%"


@pytest.mark.unit
def test_return_deadline_edge_cases_present(tmp_path: Path) -> None:
    orders = _load_jsonl(_generate(tmp_path) / "orders.jsonl")
    delivered_days: set[int] = set()
    for order in orders:
        delivered_at = order.get("delivered_at")
        if order["status"] == "delivered" and isinstance(delivered_at, str):
            parsed = datetime.fromisoformat(delivered_at.replace("Z", "+00:00"))
            delivered_days.add((TODAY - parsed).days)

    for days in (6, 7, 8, 29, 30, 31):
        assert days in delivered_days, f"nenhum pedido entregue há {days} dias"


@pytest.mark.unit
def test_zero_stock_ratio_around_fifteen_percent(tmp_path: Path) -> None:
    products = _load_jsonl(_generate(tmp_path) / "products.jsonl")
    total = 0
    zero = 0
    for product in products:
        for variant in product["variants"]:
            total += 1
            if variant["stock"] == 0:
                zero += 1

    ratio = zero / total * 100
    assert 12.0 <= ratio <= 18.0, f"ratio de estoque zero: {ratio:.2f}%"


@pytest.mark.unit
def test_generated_files_pass_contract_validation(tmp_path: Path) -> None:
    counts = validate_files(_generate(tmp_path))

    assert counts["products"] >= 290
    assert counts["customers"] >= 190
    assert counts["orders"] >= 990


@pytest.mark.unit
def test_validation_rejects_delivered_at_on_non_delivered_status() -> None:
    order = _order(
        status="paid",
        delivered_at=datetime(2026, 10, 25, tzinfo=UTC),
    )

    with pytest.raises(SeedValidationError):
        check_order(
            order,
            valid_skus={"P0001-42-PRETO"},
            valid_customers={"C0001"},
        )


@pytest.mark.unit
def test_validation_rejects_tracking_on_unshipped_order() -> None:
    order = _order(status="processing", tracking_code="TH100000001BR")

    with pytest.raises(SeedValidationError):
        check_order(
            order,
            valid_skus={"P0001-42-PRETO"},
            valid_customers={"C0001"},
        )


@pytest.mark.unit
def test_product_model_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        Product.model_validate(
            {
                "product_id": "P0001",
                "name": "Tênis",
                "brand": "Voltz",
                "category": "calcados",
                "price_cents": 28990,
                "description": "Tênis de corrida.",
                "variants": [],
                "surpresa": True,
            },
            strict=True,
        )
