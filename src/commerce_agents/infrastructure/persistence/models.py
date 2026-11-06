"""Modelos SQLAlchemy 2 das tabelas de persistência (Fase 03).

Os modelos são apenas o mapeamento relacional; as regras de negócio vivem em
``commerce_agents.domain``. O esquema deriva dos dados de seed da Fase 02.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
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


class ConfirmationTokenModel(Base):
    """Token de confirmação de uso único; só o sha256 do token é guardado (ADR 0008)."""

    __tablename__ = "confirmation_tokens"
    __table_args__ = (
        CheckConstraint("char_length(token_hash) = 64", name="ck_confirmation_tokens_hash_len"),
        CheckConstraint(
            "char_length(arguments_digest) = 64", name="ck_confirmation_tokens_digest_len"
        ),
        CheckConstraint("char_length(action) > 0", name="ck_confirmation_tokens_action_nonempty"),
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    arguments_digest: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRecordModel(Base):
    """Resultado (ou marcador pendente) registrado por ``idempotency_key`` (ADR 0011)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("char_length(key) > 0", name="ck_idempotency_records_key_nonempty"),
        CheckConstraint(
            "char_length(fingerprint) > 0", name="ck_idempotency_records_fingerprint_nonempty"
        ),
        CheckConstraint(
            "char_length(result_json) > 0", name="ck_idempotency_records_result_nonempty"
        ),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CustomerPreferenceModel(Base):
    """Preferência de longo prazo do cliente, lida como dado no prompt (ADR 0013)."""

    __tablename__ = "customer_preferences"
    __table_args__ = (
        CheckConstraint("char_length(key) > 0", name="ck_customer_preferences_key_nonempty"),
    )

    customer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("customers.customer_id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InboundMessageModel(Base):
    """Ledger de mensagens recebidas: base do efeito exatamente-uma-vez (ADR 0014)."""

    __tablename__ = "inbound_messages"
    __table_args__ = (
        CheckConstraint("status IN ('received', 'done')", name="ck_inbound_messages_status"),
    )

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="received")
    reply_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxModel(Base):
    """Transactional outbox: eventos a publicar no broker (ADR 0014)."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    inbound_message_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HandoffModel(Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'claimed', 'closed')", name="ck_handoffs_status"),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')", name="ck_handoffs_priority"
        ),
        Index(
            "uq_handoffs_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
        ),
    )

    handoff_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HandoffMessageModel(Base):
    __tablename__ = "handoff_messages"
    __table_args__ = (
        CheckConstraint("author IN ('customer', 'agent_human')", name="ck_handoff_messages_author"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    handoff_id: Mapped[str] = mapped_column(
        Text, ForeignKey("handoffs.handoff_id", ondelete="CASCADE"), nullable=False, index=True
    )
    author: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


EMBEDDING_DIMENSIONS = 384
POLICY_SEARCH_VECTOR_SQL = (
    "to_tsvector('portuguese'::regconfig, "
    "public.immutable_unaccent(title || ' ' || section || ' ' || text))"
)


class PolicyChunkModel(Base):
    """Trecho de política indexado para busca híbrida (ADR 0005 e 0012)."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        Index("ix_policy_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_policy_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_version: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(POLICY_SEARCH_VECTOR_SQL, persisted=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
