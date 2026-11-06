"""Regras de coerência e round-trip de validação do seed gerado."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from data.generators.models import (
    CATEGORIES,
    SIZES_BY_CATEGORY,
    Customer,
    Order,
    Product,
)

DELIVERED_STATUSES = frozenset({"delivered", "return_requested", "returned"})
TRACKING_STATUSES = frozenset(
    {"shipped", "in_transit", "delivered", "return_requested", "returned"}
)
RETURN_STATUSES = frozenset({"return_requested", "returned"})


class SeedValidationError(ValueError):
    """Linha do seed viola o contrato ou a coerência definida em data/README.md."""


def _parse_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def check_product(product: Product) -> None:
    """Valida coerência do catálogo além do schema Pydantic."""
    if product.category not in CATEGORIES:
        raise SeedValidationError(f"categoria inválida: {product.category}")
    allowed_sizes = SIZES_BY_CATEGORY[product.category]
    seen: set[str] = set()
    for variant in product.variants:
        if variant.size not in allowed_sizes:
            raise SeedValidationError(f"tamanho inválido {variant.size!r} para {product.category}")
        expected_sku = f"{product.product_id}-{variant.size}-{variant.color.upper()}"
        if variant.sku != expected_sku:
            raise SeedValidationError(f"sku {variant.sku!r} difere de {expected_sku!r}")
        if variant.sku in seen:
            raise SeedValidationError(f"sku duplicado: {variant.sku}")
        seen.add(variant.sku)


def check_customer(customer: Customer) -> None:
    """Valida coerência de clientes além do schema Pydantic."""
    if not customer.email.endswith("@example.com"):
        raise SeedValidationError(f"e-mail fora do domínio fictício: {customer.email}")
    if not customer.phone.startswith("+5511 90000-"):
        raise SeedValidationError(f"telefone fora do formato fictício: {customer.phone}")


def check_order(order: Order, *, valid_skus: set[str], valid_customers: set[str]) -> None:
    """Valida coerência de pedidos além do schema Pydantic."""
    if order.customer_id not in valid_customers:
        raise SeedValidationError(f"cliente inexistente: {order.customer_id}")
    if order.status in DELIVERED_STATUSES:
        if order.delivered_at is None:
            raise SeedValidationError(f"status {order.status} exige delivered_at")
        if order.delivered_at < order.created_at:
            raise SeedValidationError("delivered_at anterior a created_at")
    elif order.delivered_at is not None:
        raise SeedValidationError(f"status {order.status} não pode ter delivered_at")

    if order.status in TRACKING_STATUSES:
        if order.tracking_code is None:
            raise SeedValidationError(f"status {order.status} exige tracking_code")
    elif order.tracking_code is not None:
        raise SeedValidationError(f"status {order.status} não pode ter tracking_code")

    if order.status in RETURN_STATUSES:
        if order.return_request is None:
            raise SeedValidationError(f"status {order.status} exige return_request")
    elif order.return_request is not None:
        raise SeedValidationError(f"status {order.status} não pode ter return_request")

    if not order.items:
        raise SeedValidationError("pedido sem itens")
    for item in order.items:
        if item.sku not in valid_skus:
            raise SeedValidationError(f"sku inexistente: {item.sku}")

    total = sum(item.qty * item.unit_price_cents for item in order.items)
    if total != order.total_cents:
        raise SeedValidationError(
            f"total_cents {order.total_cents} difere da soma dos itens {total}"
        )


def validate_files(out_dir: Path) -> dict[str, int]:
    """Revalida cada linha dos arquivos gerados; retorna contagens por arquivo."""
    counts: dict[str, int] = {}

    products: list[Product] = []
    for record in _read_jsonl(out_dir / "products.jsonl"):
        products.append(Product.model_validate(record, strict=True))
    for product in products:
        check_product(product)
    counts["products"] = len(products)

    customers: list[Customer] = []
    for record in _read_jsonl(out_dir / "customers.jsonl"):
        record["created_at"] = _parse_datetime(str(record["created_at"]))
        customers.append(Customer.model_validate(record, strict=True))
    for customer in customers:
        check_customer(customer)
    counts["customers"] = len(customers)

    valid_skus = {variant.sku for product in products for variant in product.variants}
    valid_customers = {customer.customer_id for customer in customers}

    orders: list[Order] = []
    for record in _read_jsonl(out_dir / "orders.jsonl"):
        record["created_at"] = _parse_datetime(str(record["created_at"]))
        if record.get("delivered_at") is not None:
            record["delivered_at"] = _parse_datetime(str(record["delivered_at"]))
        orders.append(Order.model_validate(record, strict=True))
    for order in orders:
        check_order(order, valid_skus=valid_skus, valid_customers=valid_customers)
    counts["orders"] = len(orders)

    return counts
