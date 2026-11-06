"""Modelos SQLAlchemy 2 das tabelas de persistência (Fase 03).

Os modelos são apenas o mapeamento relacional; as regras de negócio vivem em
``commerce_agents.domain``. O esquema deriva dos dados de seed da Fase 02.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from commerce_agents.domain.order.status import OrderStatus

_ORDER_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in OrderStatus)
_CONVERSATION_STATUS_VALUES = "'open', 'handoff', 'closed'"


class Base(DeclarativeBase):
    """Base declarativa comum dos modelos de persistência."""


class CustomerModel(Base):
    """Cliente da loja."""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductModel(Base):
    """Produto do catálogo com busca lexical por nome, marca e categoria."""

    __tablename__ = "products"
    __table_args__ = (Index("ix_products_search_vector", "search_vector", postgresql_using="gin"),)

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('portuguese'::regconfig, name || ' ' || brand || ' ' || category)",
            persisted=True,
        ),
        nullable=False,
    )


class VariantModel(Base):
    """Variação de produto (tamanho/cor) com estoque."""

    __tablename__ = "product_variants"

    sku: Mapped[str] = mapped_column(Text, primary_key=True)
    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False
    )
    size: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)


class OrderModel(Base):
    """Pedido com colunas de frete e status restrito aos valores do enum."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"status IN ({_ORDER_STATUS_VALUES})", name="ck_orders_status"),
        Index("ix_orders_customer_id", "customer_id"),
    )

    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("customers.customer_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tracking_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    cep: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)


class OrderItemModel(Base):
    """Item de pedido, ordenado por posição dentro do pedido."""

    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_order_id", "order_id"),)

    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey("orders.order_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReturnRequestModel(Base):
    """Solicitação de devolução, uma por (pedido, sku)."""

    __tablename__ = "return_requests"

    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey("orders.order_id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(Text, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationModel(Base):
    """Conversa de atendimento."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_CONVERSATION_STATUS_VALUES})", name="ck_conversations_status"
        ),
    )

    conversation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageModel(Base):
    """Mensagem de uma conversa, com ``message_id`` único."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_position", "conversation_id", "position"),)

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
