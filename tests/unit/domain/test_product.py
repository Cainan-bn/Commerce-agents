"""Contrato de Product e Variant."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.domain.catalog.product import Product, Variant
from commerce_agents.domain.shared.errors import InvariantViolation
from tests.unit.domain.builders import make_product, make_variant


def test_product_exposes_contract_fields() -> None:
    product = make_product()

    assert product.product_id == "P0001"
    assert product.name == "Tênis Urban Run"
    assert product.brand == "Voltz"
    assert product.category == "calcados"
    assert product.price_cents == 28990
    assert product.variants == (make_variant(),)


def test_variant_returns_existing_variant() -> None:
    product = make_product(
        variants=(
            make_variant(sku="P0001-42-PRETO", size="42", stock=5),
            make_variant(sku="P0001-40-PRETO", size="40", stock=0),
        )
    )

    variant = product.variant("P0001-40-PRETO")

    assert variant == Variant(sku="P0001-40-PRETO", size="40", color="preto", stock=0)


def test_variant_raises_clear_domain_error_when_missing() -> None:
    product = make_product()

    with pytest.raises(InvariantViolation):
        product.variant("SKU-AUSENTE")


@pytest.mark.parametrize(("stock", "expected"), [(0, False), (1, True), (7, True)])
def test_is_in_stock(stock: int, expected: bool) -> None:
    assert make_variant(stock=stock).is_in_stock is expected


@pytest.mark.parametrize(
    ("stock", "qty", "expected"),
    [
        (0, 0, False),
        (0, 1, False),
        (1, 0, False),
        (1, 1, True),
        (5, 5, True),
        (5, 6, False),
    ],
)
def test_can_fulfill(stock: int, qty: int, expected: bool) -> None:
    assert make_variant(stock=stock).can_fulfill(qty) is expected


@given(st.integers(min_value=0, max_value=50), st.integers(min_value=-5, max_value=60))
def test_can_fulfill_property(stock: int, qty: int) -> None:
    variant = make_variant(stock=stock)

    assert variant.can_fulfill(qty) == (1 <= qty <= stock)


@given(st.integers(min_value=0, max_value=50))
def test_is_in_stock_property(stock: int) -> None:
    variant = make_variant(stock=stock)

    assert variant.is_in_stock == (stock > 0)


def test_product_variants_are_immutable_tuple() -> None:
    product = make_product()

    assert isinstance(product.variants, tuple)
    assert isinstance(product, Product)
