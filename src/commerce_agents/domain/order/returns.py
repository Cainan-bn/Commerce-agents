"""Elegibilidade de troca e devolução dentro da janela legal."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from commerce_agents.domain.order.order import Order
from commerce_agents.domain.order.status import OrderStatus

RETURN_WINDOW = timedelta(days=7)


class ReturnEligibilityReason(StrEnum):
    """Motivo do resultado da avaliação de devolução."""

    ok = "ok"
    not_delivered = "not_delivered"
    deadline_exceeded = "deadline_exceeded"
    sku_not_in_order = "sku_not_in_order"
    already_requested = "already_requested"


@dataclass(frozen=True)
class ReturnEligibility:
    """Resultado da avaliação de elegibilidade de devolução."""

    eligible: bool
    reason: ReturnEligibilityReason
    deadline: datetime | None


@dataclass(frozen=True)
class ReturnRequest:
    """Solicitação de devolução de um item do pedido."""

    order_id: str
    sku: str
    reason: str
    requested_at: datetime


def evaluate_return_eligibility(
    order: Order,
    sku: str,
    now: datetime,
    existing: tuple[ReturnRequest, ...] = (),
) -> ReturnEligibility:
    """Avalia se um SKU pode ser devolvido, considerando a janela de 7 dias."""
    if not any(item.sku == sku for item in order.items):
        return ReturnEligibility(False, ReturnEligibilityReason.sku_not_in_order, None)
    if order.status is not OrderStatus.delivered or order.delivered_at is None:
        return ReturnEligibility(False, ReturnEligibilityReason.not_delivered, None)

    deadline = order.delivered_at + RETURN_WINDOW
    if any(request.sku == sku for request in existing):
        return ReturnEligibility(False, ReturnEligibilityReason.already_requested, deadline)
    if now > deadline:
        return ReturnEligibility(False, ReturnEligibilityReason.deadline_exceeded, deadline)
    return ReturnEligibility(True, ReturnEligibilityReason.ok, deadline)
