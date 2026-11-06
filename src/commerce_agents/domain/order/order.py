"""Entidade de pedido e seus itens, com invariantes e transições."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from commerce_agents.domain.order.status import OrderStatus, can_transition
from commerce_agents.domain.shared.errors import (
    InvalidStateTransition,
    InvariantViolation,
    OrderNotCancelable,
)

_DELIVERED_STATUSES = frozenset(
    {OrderStatus.delivered, OrderStatus.return_requested, OrderStatus.returned}
)
_TRACKING_STATUSES = frozenset(
    {
        OrderStatus.shipped,
        OrderStatus.in_transit,
        OrderStatus.delivered,
        OrderStatus.return_requested,
        OrderStatus.returned,
    }
)
_CANCELABLE_STATUSES = frozenset(
    {OrderStatus.pending_payment, OrderStatus.paid, OrderStatus.processing}
)


@dataclass(frozen=True)
class OrderItem:
    """Item de um pedido, com preço unitário em centavos."""

    sku: str
    qty: int
    unit_price_cents: int


@dataclass(frozen=True)
class Order:
    """Pedido imutável cujas invariantes garantem consistência de dados."""

    order_id: str
    customer_id: str
    status: OrderStatus
    created_at: datetime
    total_cents: int
    items: tuple[OrderItem, ...]
    delivered_at: datetime | None
    tracking_code: str | None

    def __post_init__(self) -> None:
        if not self.items:
            raise InvariantViolation("pedido deve ter ao menos um item")
        for item in self.items:
            if item.qty < 1:
                raise InvariantViolation("quantidade do item deve ser >= 1")
            if item.unit_price_cents < 0:
                raise InvariantViolation("preço do item deve ser >= 0")
        if self.total_cents != sum(item.qty * item.unit_price_cents for item in self.items):
            raise InvariantViolation("total_cents difere da soma dos itens")

        delivered_like = self.status in _DELIVERED_STATUSES
        if delivered_like and self.delivered_at is None:
            raise InvariantViolation("status exige delivered_at")
        if not delivered_like and self.delivered_at is not None:
            raise InvariantViolation("status não admite delivered_at")
        if self.delivered_at is not None and self.delivered_at < self.created_at:
            raise InvariantViolation("delivered_at anterior a created_at")

        if self.status in _TRACKING_STATUSES and self.tracking_code is None:
            raise InvariantViolation("status exige tracking_code")

    @property
    def is_cancelable(self) -> bool:
        """Indica se o pedido ainda pode ser cancelado."""
        return self.status in _CANCELABLE_STATUSES

    def with_tracking(self, code: str) -> Order:
        """Retorna uma nova instância com o código de rastreio preenchido."""
        return replace(self, tracking_code=code)

    def transition_to(self, new: OrderStatus, at: datetime) -> Order:
        """Aplica uma transição de status, devolvendo uma nova instância."""
        if not can_transition(self.status, new):
            raise InvalidStateTransition(
                f"transição de {self.status.value} para {new.value} não permitida"
            )
        if new is OrderStatus.delivered and self.delivered_at is None:
            return replace(self, status=new, delivered_at=at)
        return replace(self, status=new)

    def cancel(self, at: datetime) -> Order:
        """Cancela o pedido, devolvendo uma nova instância."""
        if not self.is_cancelable:
            raise OrderNotCancelable(f"pedido em {self.status.value} não é cancelável")
        return replace(self, status=OrderStatus.cancelled)
