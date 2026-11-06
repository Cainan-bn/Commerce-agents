"""Contrato de dados do seed (data/README.md) como modelos Pydantic v2 estritos."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES: tuple[str, ...] = (
    "calcados",
    "camisetas",
    "calcas",
    "jaquetas",
    "acessorios",
)

SIZES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "calcados": tuple(str(size) for size in range(34, 47)),
    "camisetas": ("PP", "P", "M", "G", "GG"),
    "calcas": ("PP", "P", "M", "G", "GG"),
    "jaquetas": ("PP", "P", "M", "G", "GG"),
    "acessorios": ("U",),
}

ORDER_STATUSES: tuple[str, ...] = (
    "pending_payment",
    "paid",
    "processing",
    "shipped",
    "in_transit",
    "delivered",
    "cancelled",
    "return_requested",
    "returned",
)

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
