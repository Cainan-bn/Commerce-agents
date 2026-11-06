"""Estado em memória e regras da loja fake."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mock_store.models import (
    AvailabilityResponse,
    CancelResponse,
    Customer,
    Order,
    Product,
    ReturnCreateRequest,
    ReturnCreateResponse,
    ReturnEligibilityResponse,
    ShippingQuoteRequest,
    ShippingQuoteResponse,
    Variant,
)

RETURN_WINDOW = timedelta(days=7)
FREE_SHIPPING_THRESHOLD_CENTS = 29900
CANCELABLE_STATUSES = frozenset({"pending_payment", "paid", "processing"})

_CEP_REGIONS: dict[str, tuple[int, int]] = {
    "0": (1990, 2),
    "1": (2490, 3),
    "2": (2990, 3),
    "3": (3490, 4),
    "4": (3990, 5),
    "5": (4490, 6),
    "6": (4990, 7),
    "7": (3990, 5),
    "8": (2990, 4),
    "9": (3490, 5),
}


class NotFoundError(Exception):
    """Recurso inexistente na loja fake."""


class InvalidRequestError(Exception):
    """Payload inválido para as regras da loja fake."""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                loaded: Any = json.loads(stripped)
                records.append(loaded)
    return records


def _cep_region(cep: str) -> tuple[int, int]:
    digits = "".join(char for char in cep if char.isdigit())
    if not digits:
        raise InvalidRequestError("CEP inválido")
    return _CEP_REGIONS.get(digits[0], (2990, 4))


class MockStore:
    """Carrega o seed e mantém o estado mutável da loja fake."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self.products: dict[str, Product] = {}
        self.customers: dict[str, Customer] = {}
        self.orders: dict[str, Order] = {}
        self._variants_by_sku: dict[str, Variant] = {}
        self._idempotency: dict[str, tuple[int, dict[str, Any]]] = {}
        self.reload()

    def reload(self) -> None:
        products = [
            Product.model_validate(record, strict=False)
            for record in _read_jsonl(self._data_dir / "products.jsonl")
        ]
        customers = [
            Customer.model_validate(record, strict=False)
            for record in _read_jsonl(self._data_dir / "customers.jsonl")
        ]
        orders = [
            Order.model_validate(record, strict=False)
            for record in _read_jsonl(self._data_dir / "orders.jsonl")
        ]
        self.products = {product.product_id: product for product in products}
        self.customers = {customer.customer_id: customer for customer in customers}
        self.orders = {order.order_id: order for order in orders}
        self._variants_by_sku = {
            variant.sku: variant for product in products for variant in product.variants
        }
        self._idempotency = {}

    def get_order(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise NotFoundError("pedido não encontrado")
        return order

    def customer_orders(self, customer_id: str) -> list[Order]:
        if customer_id not in self.customers:
            raise NotFoundError("cliente não encontrado")
        orders = [order for order in self.orders.values() if order.customer_id == customer_id]
        return sorted(orders, key=lambda order: order.created_at, reverse=True)

    def search_products(self, query: str, limit: int) -> list[Product]:
        needle = query.strip().lower()
        matches = [
            product
            for product in self.products.values()
            if not needle
            or needle in product.name.lower()
            or needle in product.brand.lower()
            or needle in product.category.lower()
        ]
        return sorted(matches, key=lambda product: product.product_id)[:limit]

    def get_product(self, product_id: str) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise NotFoundError("produto não encontrado")
        return product

    def availability(
        self, product_id: str, size: str | None, color: str | None
    ) -> AvailabilityResponse:
        product = self.get_product(product_id)
        variants = [
            variant
            for variant in product.variants
            if (size is None or variant.size == size) and (color is None or variant.color == color)
        ]
        return AvailabilityResponse(
            product_id=product.product_id,
            available=any(variant.stock > 0 for variant in variants),
            variants=variants,
        )

    def _product_for_sku(self, sku: str) -> Product:
        variant = self._variants_by_sku.get(sku)
        if variant is None:
            raise InvalidRequestError(f"SKU desconhecido: {sku}")
        for product in self.products.values():
            if any(item.sku == sku for item in product.variants):
                return product
        raise InvalidRequestError(f"SKU desconhecido: {sku}")

    def shipping_quote(self, request: ShippingQuoteRequest) -> ShippingQuoteResponse:
        base_price, eta_days = _cep_region(request.cep)
        subtotal = sum(
            self._product_for_sku(item.sku).price_cents * item.qty for item in request.items
        )
        price_cents = 0 if subtotal >= FREE_SHIPPING_THRESHOLD_CENTS else base_price
        return ShippingQuoteResponse(price_cents=price_cents, eta_days=eta_days)

    def return_eligibility(
        self, order_id: str, sku: str, today: datetime
    ) -> ReturnEligibilityResponse:
        order = self.get_order(order_id)
        if not any(item.sku == sku for item in order.items):
            raise NotFoundError("SKU não pertence ao pedido")
        if order.status != "delivered" or order.delivered_at is None:
            return ReturnEligibilityResponse(eligible=False, reason="not_delivered", deadline=None)
        deadline = order.delivered_at + RETURN_WINDOW
        if today > deadline:
            return ReturnEligibilityResponse(
                eligible=False, reason="deadline_exceeded", deadline=deadline
            )
        return ReturnEligibilityResponse(eligible=True, reason="ok", deadline=deadline)

    def cancel(self, order_id: str, key: str, today: datetime) -> tuple[int, dict[str, Any]]:
        idem_key = f"cancel:{key}"
        cached = self._idempotency.get(idem_key)
        if cached is not None:
            return cached

        order = self.orders.get(order_id)
        result: tuple[int, dict[str, Any]]
        if order is None:
            result = (404, {"detail": "pedido não encontrado"})
        elif order.status not in CANCELABLE_STATUSES:
            result = (409, {"detail": "pedido não cancelável"})
        else:
            self.orders[order_id] = order.model_copy(update={"status": "cancelled"})
            body = CancelResponse(
                order_id=order_id, status="cancelled", cancelled_at=today
            ).model_dump(mode="json")
            result = (200, body)

        self._idempotency[idem_key] = result
        return result

    def create_return(
        self, request: ReturnCreateRequest, key: str, today: datetime
    ) -> tuple[int, dict[str, Any]]:
        idem_key = f"return:{key}"
        cached = self._idempotency.get(idem_key)
        if cached is not None:
            return cached

        order = self.orders.get(request.order_id)
        result: tuple[int, dict[str, Any]]
        if order is None:
            result = (404, {"detail": "pedido não encontrado"})
        elif order.return_request is not None and order.return_request.get("sku") == request.sku:
            result = (409, {"detail": "solicitação de devolução já existe"})
        elif not any(item.sku == request.sku for item in order.items):
            result = (404, {"detail": "SKU não pertence ao pedido"})
        else:
            eligibility = self.return_eligibility(request.order_id, request.sku, today)
            if not eligibility.eligible:
                result = (422, {"detail": eligibility.reason})
            else:
                record: dict[str, Any] = {
                    "sku": request.sku,
                    "reason": request.reason,
                    "status": "requested",
                    "requested_at": today.isoformat(),
                }
                self.orders[request.order_id] = order.model_copy(
                    update={"status": "return_requested", "return_request": record}
                )
                body = ReturnCreateResponse(
                    order_id=request.order_id,
                    sku=request.sku,
                    status="return_requested",
                    requested_at=today,
                ).model_dump(mode="json")
                result = (200, body)

        self._idempotency[idem_key] = result
        return result
