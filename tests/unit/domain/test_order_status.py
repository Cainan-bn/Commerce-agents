"""Contrato da tabela de transições de status do pedido."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.domain.order.status import (
    ALLOWED_TRANSITIONS,
    OrderStatus,
    can_transition,
)
from commerce_agents.domain.shared.errors import InvalidStateTransition
from tests.unit.domain.builders import make_order

EXPECTED_TRANSITIONS = {
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

ALL_STATUSES = list(OrderStatus)
FORBIDDEN_PAIRS = [
    (first, second)
    for first in ALL_STATUSES
    for second in ALL_STATUSES
    if second not in EXPECTED_TRANSITIONS[first]
]


def test_status_values_match_contract() -> None:
    assert {status.value for status in OrderStatus} == {
        "pending_payment",
        "paid",
        "processing",
        "shipped",
        "in_transit",
        "delivered",
        "cancelled",
        "return_requested",
        "returned",
    }


def test_allowed_transitions_table_matches_contract_exactly() -> None:
    assert dict(ALLOWED_TRANSITIONS) == EXPECTED_TRANSITIONS


@pytest.mark.parametrize("terminal", [OrderStatus.cancelled, OrderStatus.returned])
def test_terminal_states_have_no_outgoing_transitions(terminal: OrderStatus) -> None:
    assert ALLOWED_TRANSITIONS[terminal] == frozenset()


@given(st.sampled_from(ALL_STATUSES), st.sampled_from(ALL_STATUSES))
def test_can_transition_matches_allowed_transitions(
    first: OrderStatus, second: OrderStatus
) -> None:
    assert can_transition(first, second) == (second in ALLOWED_TRANSITIONS[first])


@pytest.mark.parametrize(
    ("current", "target"), sorted(FORBIDDEN_PAIRS, key=lambda p: (p[0].value, p[1].value))
)
def test_transition_to_forbidden_pair_raises(current: OrderStatus, target: OrderStatus) -> None:
    order = make_order(status=current)

    with pytest.raises(InvalidStateTransition):
        order.transition_to(target, datetime(2026, 10, 5, tzinfo=UTC))


def test_transition_to_allowed_pair_returns_new_order() -> None:
    order = make_order(status=OrderStatus.pending_payment)

    paid = order.transition_to(OrderStatus.paid, datetime(2026, 10, 2, tzinfo=UTC))

    assert paid.status is OrderStatus.paid
    assert order.status is OrderStatus.pending_payment
    assert paid is not order


def test_transition_to_delivered_sets_delivered_at() -> None:
    order = make_order(status=OrderStatus.in_transit)
    delivered_at = datetime(2026, 10, 10, 8, 30, tzinfo=UTC)

    delivered = order.transition_to(OrderStatus.delivered, delivered_at)

    assert delivered.status is OrderStatus.delivered
    assert delivered.delivered_at == delivered_at
    assert order.delivered_at is None


def test_with_tracking_allows_shipping() -> None:
    order = make_order(status=OrderStatus.processing, tracking_code=None)

    with_tracking = order.with_tracking("TH999999999BR")
    shipped = with_tracking.transition_to(OrderStatus.shipped, datetime(2026, 10, 3, tzinfo=UTC))

    assert with_tracking.tracking_code == "TH999999999BR"
    assert shipped.status is OrderStatus.shipped
    assert shipped.tracking_code == "TH999999999BR"
