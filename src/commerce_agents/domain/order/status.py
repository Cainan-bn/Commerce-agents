"""Status do pedido e tabela de transições permitidas."""

from collections.abc import Mapping
from enum import StrEnum


class OrderStatus(StrEnum):
    """Estágio do ciclo de vida de um pedido."""

    pending_payment = "pending_payment"
    paid = "paid"
    processing = "processing"
    shipped = "shipped"
    in_transit = "in_transit"
    delivered = "delivered"
    cancelled = "cancelled"
    return_requested = "return_requested"
    returned = "returned"


ALLOWED_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.pending_payment: frozenset({OrderStatus.paid, OrderStatus.cancelled}),
    OrderStatus.paid: frozenset({OrderStatus.processing, OrderStatus.cancelled}),
    OrderStatus.processing: frozenset({OrderStatus.shipped, OrderStatus.cancelled}),
    OrderStatus.shipped: frozenset({OrderStatus.in_transit}),
    OrderStatus.in_transit: frozenset({OrderStatus.delivered}),
    OrderStatus.delivered: frozenset({OrderStatus.return_requested}),
    OrderStatus.return_requested: frozenset({OrderStatus.returned, OrderStatus.delivered}),
    OrderStatus.cancelled: frozenset(),
    OrderStatus.returned: frozenset(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    """Indica se a transição de ``current`` para ``target`` é permitida."""
    return target in ALLOWED_TRANSITIONS[current]
