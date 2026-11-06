"""Contrato de invariantes, cancelamento e imutabilidade de Order."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from commerce_agents.domain.order.order import OrderItem
from commerce_agents.domain.order.status import OrderStatus
from commerce_agents.domain.shared.errors import InvariantViolation, OrderNotCancelable
from tests.unit.domain.builders import BASE_TIME, make_item, make_order

CANCELABLE_STATUSES = {
    OrderStatus.pending_payment,
    OrderStatus.paid,
    OrderStatus.processing,
}
ALL_STATUSES = list(OrderStatus)


def test_valid_order_is_constructed() -> None:
    order = make_order()

    assert order.order_id == "O000001"
    assert order.status is OrderStatus.pending_payment
    assert order.total_cents == 1000
    assert order.items == (OrderItem(sku="SKU-1", qty=1, unit_price_cents=1000),)


def test_order_without_items_violates_invariant() -> None:
    with pytest.raises(InvariantViolation):
        make_order(items=(), total_cents=0)


def test_item_with_qty_below_one_violates_invariant() -> None:
    with pytest.raises(InvariantViolation):
        make_order(items=(make_item(qty=0),))


def test_item_with_negative_price_violates_invariant() -> None:
    with pytest.raises(InvariantViolation):
        make_order(items=(make_item(unit_price_cents=-1),))


def test_total_must_equal_items_sum() -> None:
    with pytest.raises(InvariantViolation):
        make_order(items=(make_item(qty=2, unit_price_cents=1000),), total_cents=1000)


def test_delivered_at_present_only_for_delivered_like_statuses() -> None:
    with pytest.raises(InvariantViolation):
        make_order(status=OrderStatus.paid, delivered_at=BASE_TIME)

    with pytest.raises(InvariantViolation):
        make_order(status=OrderStatus.delivered, delivered_at=None)


def test_tracking_required_from_shipped_onward() -> None:
    with pytest.raises(InvariantViolation):
        make_order(status=OrderStatus.shipped, tracking_code=None)


def test_delivered_at_cannot_precede_created_at() -> None:
    with pytest.raises(InvariantViolation):
        make_order(
            status=OrderStatus.delivered,
            created_at=datetime(2026, 10, 10, tzinfo=UTC),
            delivered_at=datetime(2026, 10, 9, tzinfo=UTC),
        )


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_is_cancelable_only_for_cancelable_statuses(status: OrderStatus) -> None:
    order = make_order(status=status)

    assert order.is_cancelable == (status in CANCELABLE_STATUSES)


@pytest.mark.parametrize(
    "status",
    sorted(CANCELABLE_STATUSES, key=lambda item: item.value),
)
def test_cancel_returns_new_cancelled_order_without_mutating_original(
    status: OrderStatus,
) -> None:
    order = make_order(status=status)
    cancelled_at = datetime(2026, 10, 4, tzinfo=UTC)

    cancelled = order.cancel(cancelled_at)

    assert cancelled.status is OrderStatus.cancelled
    assert cancelled is not order
    assert order.status is status
    assert cancelled.order_id == order.order_id
    assert cancelled.items == order.items


@pytest.mark.parametrize(
    "status",
    [status for status in ALL_STATUSES if status not in CANCELABLE_STATUSES],
)
def test_cancel_in_non_cancelable_status_raises(status: OrderStatus) -> None:
    order = make_order(status=status)

    with pytest.raises(OrderNotCancelable):
        order.cancel(datetime(2026, 10, 4, tzinfo=UTC))


def test_order_is_frozen() -> None:
    order = make_order()

    with pytest.raises(FrozenInstanceError):
        order.status = OrderStatus.paid  # type: ignore[misc]


def test_order_equality_is_structural() -> None:
    assert make_order() == make_order()
    assert make_order(order_id="O000002") != make_order()


def test_cancelled_order_is_not_cancelable() -> None:
    cancelled = make_order(status=OrderStatus.pending_payment).cancel(BASE_TIME)

    assert cancelled.is_cancelable is False


def test_order_exposes_items_immutably() -> None:
    order = make_order()

    with pytest.raises(FrozenInstanceError):
        order.items = ()  # type: ignore[misc]
