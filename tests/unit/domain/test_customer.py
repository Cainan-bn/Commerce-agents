"""Contrato da entidade Customer."""

from dataclasses import FrozenInstanceError

import pytest

from commerce_agents.domain.customer.customer import Customer
from tests.unit.domain.builders import BASE_TIME, make_customer


def test_customer_exposes_contract_fields() -> None:
    customer = make_customer()

    assert customer.customer_id == "C0001"
    assert customer.name == "Maria Fictícia"
    assert customer.email == "maria@example.com"
    assert customer.phone == "+5511 90000-0001"
    assert customer.created_at == BASE_TIME


def test_customer_is_immutable() -> None:
    customer = make_customer()

    with pytest.raises(FrozenInstanceError):
        customer.name = "Outro Nome"  # type: ignore[misc]


def test_customer_equality_is_structural() -> None:
    assert make_customer() == make_customer()
    assert make_customer(customer_id="C0002") != make_customer()


def test_customer_is_a_domain_type() -> None:
    assert isinstance(make_customer(), Customer)
