"""Fábricas de objetos de domínio válidos para os testes contratuais."""

from datetime import UTC, datetime, timedelta
from typing import Any

from commerce_agents.domain.catalog.product import Product, Variant
from commerce_agents.domain.conversation.conversation import (
    Conversation,
    ConversationStatus,
    Message,
)
from commerce_agents.domain.customer.customer import Customer
from commerce_agents.domain.order.order import Order, OrderItem
from commerce_agents.domain.order.returns import ReturnRequest
from commerce_agents.domain.order.status import OrderStatus

BASE_TIME = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

DELIVERED_STATUSES = frozenset(
    {OrderStatus.delivered, OrderStatus.return_requested, OrderStatus.returned}
)
TRACKING_STATUSES = frozenset(
    {
        OrderStatus.shipped,
        OrderStatus.in_transit,
        OrderStatus.delivered,
        OrderStatus.return_requested,
        OrderStatus.returned,
    }
)

_UNSET: Any = object()


def make_item(sku: str = "SKU-1", qty: int = 1, unit_price_cents: int = 1000) -> OrderItem:
    return OrderItem(sku=sku, qty=qty, unit_price_cents=unit_price_cents)


def make_order(
    *,
    order_id: str = "O000001",
    customer_id: str = "C0001",
    status: OrderStatus = OrderStatus.pending_payment,
    created_at: datetime = BASE_TIME,
    items: tuple[OrderItem, ...] | None = None,
    total_cents: int | None | Any = _UNSET,
    delivered_at: datetime | None | Any = _UNSET,
    tracking_code: str | None | Any = _UNSET,
) -> Order:
    order_items = items if items is not None else (make_item(),)
    computed_total = sum(item.qty * item.unit_price_cents for item in order_items)
    if total_cents is _UNSET:
        total_cents = computed_total
    if delivered_at is _UNSET:
        delivered_at = created_at + timedelta(days=2) if status in DELIVERED_STATUSES else None
    if tracking_code is _UNSET:
        tracking_code = "TH123456789BR" if status in TRACKING_STATUSES else None
    return Order(
        order_id=order_id,
        customer_id=customer_id,
        status=status,
        created_at=created_at,
        total_cents=total_cents,
        items=order_items,
        delivered_at=delivered_at,
        tracking_code=tracking_code,
    )


def make_return_request(
    *,
    order_id: str = "O000001",
    sku: str = "SKU-1",
    reason: str = "defeito",
    requested_at: datetime = BASE_TIME,
) -> ReturnRequest:
    return ReturnRequest(order_id=order_id, sku=sku, reason=reason, requested_at=requested_at)


def make_customer(
    *,
    customer_id: str = "C0001",
    name: str = "Maria Fictícia",
    email: str = "maria@example.com",
    phone: str = "+5511 90000-0001",
    created_at: datetime = BASE_TIME,
) -> Customer:
    return Customer(
        customer_id=customer_id,
        name=name,
        email=email,
        phone=phone,
        created_at=created_at,
    )


def make_variant(
    *,
    sku: str = "P0001-42-PRETO",
    size: str = "42",
    color: str = "preto",
    stock: int = 5,
) -> Variant:
    return Variant(sku=sku, size=size, color=color, stock=stock)


def make_product(
    *,
    product_id: str = "P0001",
    name: str = "Tênis Urban Run",
    brand: str = "Voltz",
    category: str = "calcados",
    price_cents: int = 28990,
    description: str = "Tênis de corrida urbano.",
    variants: tuple[Variant, ...] | None = None,
) -> Product:
    return Product(
        product_id=product_id,
        name=name,
        brand=brand,
        category=category,
        price_cents=price_cents,
        description=description,
        variants=variants if variants is not None else (make_variant(),),
    )


def make_message(
    *,
    message_id: str = "MSG-1",
    text: str = "olá",
    sent_at: datetime = BASE_TIME,
) -> Message:
    return Message(message_id=message_id, text=text, sent_at=sent_at)


def make_conversation(
    *,
    conversation_id: str = "CONV-1",
    status: ConversationStatus = ConversationStatus.open,
    messages: tuple[Message, ...] | None = None,
    created_at: datetime = BASE_TIME,
) -> Conversation:
    return Conversation(
        conversation_id=conversation_id,
        status=status,
        messages=messages if messages is not None else (),
        created_at=created_at,
    )
