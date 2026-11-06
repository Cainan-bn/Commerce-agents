"""Geração determinística dos pedidos da TH Multimarcas."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from data.generators.models import Customer, Order, OrderItem, OrderStatus, Product, ShippingInfo

TODAY = datetime(2026, 11, 1, tzinfo=UTC)

ORDER_COUNT = 1000

STATUS_TARGET: dict[OrderStatus, int] = {
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

EDGE_DAYS: tuple[int, ...] = (6, 7, 8, 29, 30, 31)

TRACKING_STATUSES = frozenset(
    {"shipped", "in_transit", "delivered", "return_requested", "returned"}
)
RETURN_STATUSES = frozenset({"return_requested", "returned"})

RETURN_REASONS: tuple[str, ...] = (
    "tamanho errado",
    "defeito",
    "arrependimento",
    "produto diferente do anunciado",
)

CREATED_DAYS_BY_STATUS: dict[OrderStatus, tuple[int, int]] = {
    "pending_payment": (1, 3),
    "paid": (2, 4),
    "processing": (3, 6),
    "shipped": (4, 7),
    "in_transit": (5, 9),
    "cancelled": (1, 7),
}

DELIVERED_DAYS_BY_STATUS: dict[OrderStatus, tuple[int, int]] = {
    "delivered": (8, 90),
    "return_requested": (3, 7),
    "returned": (8, 60),
}


def _days_ago(rng: random.Random, days: int) -> datetime:
    day = TODAY - timedelta(days=days)
    return day.replace(hour=rng.randint(8, 21), minute=rng.randint(0, 59), second=0, microsecond=0)


def _midnight(days: int) -> datetime:
    return TODAY - timedelta(days=days)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _timeline(
    rng: random.Random, status: OrderStatus, forced_delivered_days: int | None
) -> tuple[datetime, datetime | None]:
    if forced_delivered_days is not None:
        delivered_at = _midnight(forced_delivered_days)
        created_at = _days_ago(rng, forced_delivered_days + rng.randint(2, 6))
        return created_at, delivered_at

    if status in DELIVERED_DAYS_BY_STATUS:
        lo, hi = DELIVERED_DAYS_BY_STATUS[status]
        delivered_days = rng.randint(lo, hi)
        delivered_at = _midnight(delivered_days)
        created_at = _days_ago(rng, delivered_days + rng.randint(2, 6))
        return created_at, delivered_at

    lo, hi = CREATED_DAYS_BY_STATUS[status]
    return _days_ago(rng, rng.randint(lo, hi)), None


def _pick_customer(rng: random.Random, customers: list[Customer], created_at: datetime) -> Customer:
    eligible = [customer for customer in customers if customer.created_at <= created_at]
    return rng.choice(eligible)


def _build_items(rng: random.Random, products: list[Product]) -> list[OrderItem]:
    count = 1 if rng.random() < 0.8 else rng.randint(2, 3)
    chosen = rng.sample(products, k=count)
    return [
        OrderItem(
            sku=rng.choice(product.variants).sku,
            qty=rng.randint(1, 3),
            unit_price_cents=product.price_cents,
        )
        for product in chosen
    ]


def _tracking_code(order_id: str) -> str:
    number = int(order_id[1:])
    return f"TH{100000000 + number}BR"


def _cep(rng: random.Random) -> str:
    return f"{rng.randint(0, 99999):05d}-{rng.randint(0, 999):03d}"


def _method(rng: random.Random) -> str:
    return "standard" if rng.random() < 0.85 else "express"


def _return_request(
    rng: random.Random, status: OrderStatus, sku: str, delivered_at: datetime
) -> dict[str, str]:
    requested_at = delivered_at + timedelta(days=rng.randint(1, 3))
    return {
        "sku": sku,
        "reason": rng.choice(RETURN_REASONS),
        "status": "completed" if status == "returned" else "requested",
        "requested_at": _iso(requested_at),
    }


def _build_order(
    rng: random.Random,
    order_id: str,
    status: OrderStatus,
    products: list[Product],
    customers: list[Customer],
    forced_delivered_days: int | None = None,
) -> Order:
    created_at, delivered_at = _timeline(rng, status, forced_delivered_days)
    customer = _pick_customer(rng, customers, created_at)
    items = _build_items(rng, products)
    total_cents = sum(item.qty * item.unit_price_cents for item in items)
    return_request = None
    if status in RETURN_STATUSES and delivered_at is not None:
        return_request = _return_request(rng, status, items[0].sku, delivered_at)

    return Order(
        order_id=order_id,
        customer_id=customer.customer_id,
        status=status,
        created_at=created_at,
        delivered_at=delivered_at,
        tracking_code=_tracking_code(order_id) if status in TRACKING_STATUSES else None,
        total_cents=total_cents,
        items=items,
        shipping=ShippingInfo(carrier="Correios", cep=_cep(rng), method=_method(rng)),
        return_request=return_request,
    )


def generate_orders(
    rng: random.Random, products: list[Product], customers: list[Customer]
) -> list[Order]:
    """Gera ~1.000 pedidos com status coerentes e casos de borda de prazo."""
    statuses: list[OrderStatus] = []
    for status, count in STATUS_TARGET.items():
        effective = count - len(EDGE_DAYS) if status == "delivered" else count
        statuses.extend([status] * effective)
    rng.shuffle(statuses)

    orders: list[Order] = []
    for days in EDGE_DAYS:
        order_id = f"O{len(orders) + 1:06d}"
        orders.append(_build_order(rng, order_id, "delivered", products, customers, days))

    for status in statuses:
        order_id = f"O{len(orders) + 1:06d}"
        orders.append(_build_order(rng, order_id, status, products, customers))

    return orders


RECENT_REDATE_CONSTANT = 1_000_000
RECENT_DELIVERY_TARGET = 45


def redate_recent_deliveries(orders: list[Order], seed: int) -> list[Order]:
    """Redata um subconjunto determinístico de entregas para a janela de troca.

    Usa um gerador separado (``seed + RECENT_REDATE_CONSTANT``) e só altera pedidos
    ``delivered`` com id maior que O000100, preservando byte a byte os 100 primeiros
    pedidos e a sequência de sorteios do gerador principal.
    """
    rng = random.Random(seed + RECENT_REDATE_CONSTANT)
    candidates = [
        order for order in orders if order.status == "delivered" and int(order.order_id[1:]) > 100
    ]
    selected_ids = {order.order_id for order in rng.sample(candidates, k=RECENT_DELIVERY_TARGET)}

    redated: list[Order] = []
    for order in orders:
        if order.order_id in selected_ids:
            days = rng.randint(1, 7)
            delivered_at = (TODAY - timedelta(days=days)).replace(
                hour=rng.randint(8, 21), minute=rng.randint(0, 59), second=0, microsecond=0
            )
            order = order.model_copy(update={"delivered_at": delivered_at})
        redated.append(order)
    return redated
