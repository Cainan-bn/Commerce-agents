"""Contrato de elegibilidade de troca/devolução."""

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.domain.order.order import Order
from commerce_agents.domain.order.returns import (
    RETURN_WINDOW,
    ReturnEligibilityReason,
    evaluate_return_eligibility,
)
from commerce_agents.domain.order.status import OrderStatus
from tests.unit.domain.builders import (
    BASE_TIME,
    make_order,
    make_return_request,
)

DELIVERED_AT = BASE_TIME


def _delivered_order() -> Order:
    return make_order(
        status=OrderStatus.delivered,
        created_at=BASE_TIME,
        delivered_at=DELIVERED_AT,
    )


def test_return_window_is_seven_days() -> None:
    assert RETURN_WINDOW == timedelta(days=7)


def test_reason_values_match_contract() -> None:
    assert {reason.value for reason in ReturnEligibilityReason} == {
        "ok",
        "not_delivered",
        "deadline_exceeded",
        "sku_not_in_order",
        "already_requested",
    }


def test_eligible_on_inclusive_deadline() -> None:
    order = _delivered_order()
    now = DELIVERED_AT + RETURN_WINDOW

    eligibility = evaluate_return_eligibility(order, "SKU-1", now)

    assert eligibility.eligible is True
    assert eligibility.reason is ReturnEligibilityReason.ok
    assert eligibility.deadline == DELIVERED_AT + RETURN_WINDOW


def test_ineligible_one_second_after_deadline() -> None:
    order = _delivered_order()
    now = DELIVERED_AT + RETURN_WINDOW + timedelta(seconds=1)

    eligibility = evaluate_return_eligibility(order, "SKU-1", now)

    assert eligibility.eligible is False
    assert eligibility.reason is ReturnEligibilityReason.deadline_exceeded
    assert eligibility.deadline == DELIVERED_AT + RETURN_WINDOW


def test_not_delivered_has_no_deadline() -> None:
    order = make_order(status=OrderStatus.shipped)

    eligibility = evaluate_return_eligibility(order, "SKU-1", BASE_TIME)

    assert eligibility.eligible is False
    assert eligibility.reason is ReturnEligibilityReason.not_delivered
    assert eligibility.deadline is None


def test_sku_not_in_order_has_no_deadline() -> None:
    order = _delivered_order()

    eligibility = evaluate_return_eligibility(order, "SKU-AUSENTE", BASE_TIME)

    assert eligibility.eligible is False
    assert eligibility.reason is ReturnEligibilityReason.sku_not_in_order
    assert eligibility.deadline is None


def test_already_requested_keeps_deadline() -> None:
    order = _delivered_order()
    existing = (make_return_request(sku="SKU-1", requested_at=BASE_TIME),)

    eligibility = evaluate_return_eligibility(order, "SKU-1", BASE_TIME, existing=existing)

    assert eligibility.eligible is False
    assert eligibility.reason is ReturnEligibilityReason.already_requested
    assert eligibility.deadline == DELIVERED_AT + RETURN_WINDOW


def test_sku_check_runs_before_not_delivered() -> None:
    order = make_order(status=OrderStatus.shipped)

    eligibility = evaluate_return_eligibility(order, "SKU-AUSENTE", BASE_TIME)

    assert eligibility.reason is ReturnEligibilityReason.sku_not_in_order


def test_not_delivered_runs_before_already_requested() -> None:
    order = make_order(status=OrderStatus.shipped)
    existing = (make_return_request(sku="SKU-1", requested_at=BASE_TIME),)

    eligibility = evaluate_return_eligibility(order, "SKU-1", BASE_TIME, existing=existing)

    assert eligibility.reason is ReturnEligibilityReason.not_delivered


def test_already_requested_runs_before_deadline_exceeded() -> None:
    order = _delivered_order()
    existing = (make_return_request(sku="SKU-1", requested_at=BASE_TIME),)
    now = DELIVERED_AT + RETURN_WINDOW + timedelta(days=30)

    eligibility = evaluate_return_eligibility(order, "SKU-1", now, existing=existing)

    assert eligibility.reason is ReturnEligibilityReason.already_requested


def test_existing_request_for_other_sku_does_not_block() -> None:
    order = _delivered_order()
    existing = (make_return_request(sku="SKU-OUTRO", requested_at=BASE_TIME),)

    eligibility = evaluate_return_eligibility(order, "SKU-1", BASE_TIME, existing=existing)

    assert eligibility.eligible is True


@pytest.mark.parametrize("status", [OrderStatus.pending_payment, OrderStatus.returned])
def test_only_delivered_is_eligible_for_return(status: OrderStatus) -> None:
    order = make_order(status=status)

    eligibility = evaluate_return_eligibility(order, "SKU-1", BASE_TIME)

    assert eligibility.eligible is False


@given(st.integers(min_value=-86400, max_value=86400 * 10))
def test_eligibility_boundary_is_exactly_seven_days(delta_seconds: int) -> None:
    order = _delivered_order()
    now = DELIVERED_AT + timedelta(seconds=delta_seconds)

    eligibility = evaluate_return_eligibility(order, "SKU-1", now)

    assert eligibility.eligible == (delta_seconds <= RETURN_WINDOW.total_seconds())
    expected_reason = (
        ReturnEligibilityReason.ok
        if eligibility.eligible
        else ReturnEligibilityReason.deadline_exceeded
    )
    assert eligibility.reason is expected_reason
