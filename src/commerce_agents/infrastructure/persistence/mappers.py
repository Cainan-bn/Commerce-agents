"""Conversões entre modelos ORM e entidades/DTOs do domínio."""

from __future__ import annotations

from commerce_agents.application.dto.views import OrderView, ProductView, VariantAvailability
from commerce_agents.domain.conversation.conversation import (
    Conversation,
    ConversationStatus,
    Message,
)
from commerce_agents.domain.customer.customer import Customer
from commerce_agents.domain.order.order import Order, OrderItem
from commerce_agents.domain.order.returns import ReturnRequest
from commerce_agents.domain.order.status import OrderStatus
from commerce_agents.infrastructure.persistence.models import (
    ConversationModel,
    CustomerModel,
    MessageModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    ReturnRequestModel,
    VariantModel,
)

_EMPTY_SHIPPING = {"carrier": "", "cep": "", "method": ""}


def customer_to_model(customer: Customer) -> CustomerModel:
    return CustomerModel(
        customer_id=customer.customer_id,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        created_at=customer.created_at,
    )


def customer_from_model(model: CustomerModel) -> Customer:
    return Customer(
        customer_id=model.customer_id,
        name=model.name,
        email=model.email,
        phone=model.phone,
        created_at=model.created_at,
    )


def order_to_model(order: Order) -> OrderModel:
    return OrderModel(
        order_id=order.order_id,
        customer_id=order.customer_id,
        status=order.status.value,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        tracking_code=order.tracking_code,
        total_cents=order.total_cents,
        **_EMPTY_SHIPPING,
    )


def order_item_to_model(item: OrderItem, order_id: str, position: int) -> OrderItemModel:
    return OrderItemModel(
        order_id=order_id,
        position=position,
        sku=item.sku,
        qty=item.qty,
        unit_price_cents=item.unit_price_cents,
    )


def order_from_models(model: OrderModel, items: list[OrderItemModel]) -> Order:
    return Order(
        order_id=model.order_id,
        customer_id=model.customer_id,
        status=OrderStatus(model.status),
        created_at=model.created_at,
        total_cents=model.total_cents,
        items=tuple(
            OrderItem(sku=item.sku, qty=item.qty, unit_price_cents=item.unit_price_cents)
            for item in items
        ),
        delivered_at=model.delivered_at,
        tracking_code=model.tracking_code,
    )


def order_to_view(model: OrderModel) -> OrderView:
    return OrderView(
        order_id=model.order_id,
        customer_id=model.customer_id,
        status=model.status,
        tracking_code=model.tracking_code,
        created_at=model.created_at,
        delivered_at=model.delivered_at,
        total_cents=model.total_cents,
    )


def return_request_from_model(model: ReturnRequestModel) -> ReturnRequest:
    return ReturnRequest(
        order_id=model.order_id,
        sku=model.sku,
        reason=model.reason,
        requested_at=model.requested_at,
    )


def conversation_to_model(conversation: Conversation) -> ConversationModel:
    return ConversationModel(
        conversation_id=conversation.conversation_id,
        status=conversation.status.value,
        created_at=conversation.created_at,
    )


def conversation_from_models(
    model: ConversationModel, messages: list[MessageModel]
) -> Conversation:
    return Conversation(
        conversation_id=model.conversation_id,
        status=ConversationStatus(model.status),
        messages=tuple(
            Message(message_id=message.message_id, text=message.text, sent_at=message.sent_at)
            for message in messages
        ),
        created_at=model.created_at,
    )


def product_to_view(model: ProductModel, variants: list[VariantModel]) -> ProductView:
    return ProductView(
        product_id=model.product_id,
        name=model.name,
        brand=model.brand,
        price_cents=model.price_cents,
        variants=tuple(
            VariantAvailability(
                sku=variant.sku,
                size=variant.size,
                color=variant.color,
                stock=variant.stock,
            )
            for variant in variants
        ),
    )
