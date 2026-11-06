"""Testes de realismo do seed: entregas recentes e pedidos congelados."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from data.generators.generate import generate

TODAY = datetime(2026, 11, 1, tzinfo=UTC)
FROZEN_SHA256 = (
    "3ce325f6e478f66417b4530b8f61fbbac1cc698e4bfa44d4532d0d0ace4b2d81"  # pragma: allowlist secret
)

STATUS_COUNTS = {
    "delivered": 450,
    "in_transit": 120,
    "shipped": 80,
    "processing": 80,
    "paid": 60,
    "pending_payment": 50,
    "cancelled": 80,
    "return_requested": 40,
    "returned": 40,
}


def _generate(tmp_path: Path, seed: int = 42) -> Path:
    out = tmp_path / "seed"
    generate(seed, out)
    return out


def _orders(out: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (out / "orders.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _first_100_sha256(out: Path) -> str:
    lines = (out / "orders.jsonl").read_text(encoding="utf-8").splitlines()[:100]
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _days_since(delivered_at: str) -> int:
    parsed = datetime.fromisoformat(delivered_at.replace("Z", "+00:00"))
    return (TODAY - parsed).days


@pytest.mark.unit
def test_recent_deliveries_within_exchange_window(tmp_path: Path) -> None:
    orders = _orders(_generate(tmp_path))
    recent = [
        order
        for order in orders
        if order["status"] == "delivered"
        and isinstance(order["delivered_at"], str)
        and 0 <= _days_since(order["delivered_at"]) <= 6
    ]
    assert len(recent) >= 40


@pytest.mark.unit
def test_first_100_orders_are_frozen(tmp_path: Path) -> None:
    assert _first_100_sha256(_generate(tmp_path)) == FROZEN_SHA256


@pytest.mark.unit
def test_generator_is_deterministic(tmp_path: Path) -> None:
    first = _generate(tmp_path / "a")
    second = _generate(tmp_path / "b")
    for name in ("products.jsonl", "customers.jsonl", "orders.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


@pytest.mark.unit
def test_status_distribution_unchanged(tmp_path: Path) -> None:
    orders = _orders(_generate(tmp_path))
    counts = Counter(str(order["status"]) for order in orders)
    assert dict(counts) == STATUS_COUNTS


@pytest.mark.unit
def test_created_before_delivered(tmp_path: Path) -> None:
    orders = _orders(_generate(tmp_path))
    for order in orders:
        if order["delivered_at"] is None:
            continue
        created = datetime.fromisoformat(str(order["created_at"]).replace("Z", "+00:00"))
        delivered = datetime.fromisoformat(str(order["delivered_at"]).replace("Z", "+00:00"))
        assert created < delivered, order["order_id"]
