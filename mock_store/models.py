"""Modelos Pydantic v2 estritos da API fake da loja."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Variant(StrictModel):
    sku: str
    size: str
    color: str
    stock: int = Field(ge=0)


class Product(StrictModel):
    product_id: str
    name: str
    brand: str
    category: str
    price_cents: int = Field(ge=0)
    description: str
    variants: list[Variant]


class Customer(StrictModel):
    customer_id: str
    name: str
    email: str
    phone: str
    created_at: datetime


OrderStatus = Literal[
    "pending_payment",
    "paid",
    "processing",
    "shipped",
    "in_transit",
    "delivered",
    "cancelled",
    "return_requested",
    "returned",
]


class OrderItem(StrictModel):
    sku: str
    qty: int = Field(ge=1)
    unit_price_cents: int = Field(ge=0)


class ShippingInfo(StrictModel):
    carrier: str
    cep: str
    method: str


class Order(StrictModel):
    order_id: str
    customer_id: str
    status: OrderStatus
    created_at: datetime
    delivered_at: datetime | None = None
    tracking_code: str | None = None
    total_cents: int = Field(ge=0)
    items: list[OrderItem]
    shipping: ShippingInfo
    return_request: dict[str, Any] | None = None


class AvailabilityResponse(StrictModel):
    product_id: str
    available: bool
    variants: list[Variant]


class ShippingQuoteItem(StrictModel):
    sku: str
    qty: int = Field(ge=1)


class ShippingQuoteRequest(StrictModel):
    cep: str = Field(min_length=1)
    items: list[ShippingQuoteItem] = Field(min_length=1)


class ShippingQuoteResponse(StrictModel):
    price_cents: int = Field(ge=0)
    eta_days: int = Field(ge=0)


class ReturnEligibilityResponse(StrictModel):
    eligible: bool
    reason: str
    deadline: datetime | None


class ReturnCreateRequest(StrictModel):
    order_id: str
    sku: str
    reason: str = Field(min_length=1)


class ReturnCreateResponse(StrictModel):
    order_id: str
    sku: str
    status: Literal["return_requested"]
    requested_at: datetime


class CancelResponse(StrictModel):
    order_id: str
    status: Literal["cancelled"]
    cancelled_at: datetime


class AdminResetResponse(StrictModel):
    status: Literal["reset"]
