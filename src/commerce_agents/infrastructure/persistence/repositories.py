"""Repositórios SQL que implementam os ports de ``application/ports``."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.application.dto.views import OrderView, ProductView
from commerce_agents.domain.conversation.conversation import Conversation
from commerce_agents.domain.customer.customer import Customer
from commerce_agents.domain.order.order import Order
from commerce_agents.domain.order.returns import ReturnRequest
from commerce_agents.infrastructure.persistence.mappers import (
    conversation_from_models,
    conversation_to_model,
    customer_from_model,
    customer_to_model,
    order_from_models,
    order_item_to_model,
    order_to_model,
    order_to_view,
    product_to_view,
    return_request_from_model,
)
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


class SqlOrderRepository:
    """Acesso a pedidos, com upsert transacional de itens."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, order_id: str) -> OrderView | None:
        async with self._session_factory() as session, session.begin():
            model = await session.get(OrderModel, order_id)
            return order_to_view(model) if model is not None else None

    async def find(self, order_id: str) -> Order | None:
        async with self._session_factory() as session, session.begin():
            model = await session.get(OrderModel, order_id)
            if model is None:
                return None
            items = (
                (
                    await session.execute(
                        select(OrderItemModel)
                        .where(OrderItemModel.order_id == order_id)
                        .order_by(OrderItemModel.position)
                    )
                )
                .scalars()
                .all()
            )
            return order_from_models(model, list(items))

    async def save(self, order: Order) -> None:
        async with self._session_factory() as session, session.begin():
            new = order_to_model(order)
            existing = await session.get(OrderModel, order.order_id)
            if existing is None:
                session.add(new)
            else:
                # frete não pertence ao domínio Order: nunca é sobrescrito
                existing.customer_id = new.customer_id
                existing.status = new.status
                existing.created_at = new.created_at
                existing.delivered_at = new.delivered_at
                existing.tracking_code = new.tracking_code
                existing.total_cents = new.total_cents
            await session.execute(
                delete(OrderItemModel).where(OrderItemModel.order_id == order.order_id)
            )
            for position, item in enumerate(order.items):
                session.add(order_item_to_model(item, order.order_id, position))

    async def list_by_customer(self, customer_id: str) -> list[OrderView]:
        async with self._session_factory() as session, session.begin():
            models = (
                (
                    await session.execute(
                        select(OrderModel)
                        .where(OrderModel.customer_id == customer_id)
                        .order_by(OrderModel.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            return [order_to_view(model) for model in models]


class SqlCustomerRepository:
    """Acesso a clientes, com upsert por ``customer_id``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, customer_id: str) -> Customer | None:
        async with self._session_factory() as session, session.begin():
            model = await session.get(CustomerModel, customer_id)
            return customer_from_model(model) if model is not None else None

    async def save(self, customer: Customer) -> None:
        async with self._session_factory() as session, session.begin():
            await session.merge(customer_to_model(customer))


class SqlReturnRequestRepository:
    """Solicitações de devolução, idempotentes por ``(order_id, sku)``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, request: ReturnRequest) -> None:
        async with self._session_factory() as session, session.begin():
            statement = (
                pg_insert(ReturnRequestModel)
                .values(
                    order_id=request.order_id,
                    sku=request.sku,
                    reason=request.reason,
                    requested_at=request.requested_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[ReturnRequestModel.order_id, ReturnRequestModel.sku]
                )
            )
            await session.execute(statement)

    async def list_for_order(self, order_id: str) -> tuple[ReturnRequest, ...]:
        async with self._session_factory() as session, session.begin():
            models = (
                (
                    await session.execute(
                        select(ReturnRequestModel)
                        .where(ReturnRequestModel.order_id == order_id)
                        .order_by(ReturnRequestModel.requested_at)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(return_request_from_model(model) for model in models)


class SqlConversationRepository:
    """Persistência de conversas e mensagens, idempotente por ``message_id``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, conversation_id: str) -> Conversation | None:
        async with self._session_factory() as session, session.begin():
            model = await session.get(ConversationModel, conversation_id)
            if model is None:
                return None
            messages = (
                (
                    await session.execute(
                        select(MessageModel)
                        .where(MessageModel.conversation_id == conversation_id)
                        .order_by(MessageModel.position)
                    )
                )
                .scalars()
                .all()
            )
            return conversation_from_models(model, list(messages))

    async def save(self, conversation: Conversation) -> None:
        async with self._session_factory() as session, session.begin():
            await session.merge(conversation_to_model(conversation))
            for position, message in enumerate(conversation.messages):
                statement = (
                    pg_insert(MessageModel)
                    .values(
                        message_id=message.message_id,
                        conversation_id=conversation.conversation_id,
                        position=position,
                        text=message.text,
                        sent_at=message.sent_at,
                    )
                    .on_conflict_do_nothing(index_elements=[MessageModel.message_id])
                )
                await session.execute(statement)


class SqlCatalogSearch:
    """Busca de catálogo via tsvector com suporte a consultas sem acento."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def search(self, query: str, limit: int = 5) -> list[ProductView]:
        async with self._session_factory() as session, session.begin():
            tsquery = func.websearch_to_tsquery("portuguese", func.immutable_unaccent(query))
            products = (
                (
                    await session.execute(
                        select(ProductModel)
                        .where(ProductModel.search_vector.op("@@")(tsquery))
                        .order_by(
                            func.ts_rank(ProductModel.search_vector, tsquery).desc(),
                            ProductModel.product_id,
                        )
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            if not products:
                return []

            product_ids = [product.product_id for product in products]
            variants = (
                (
                    await session.execute(
                        select(VariantModel)
                        .where(VariantModel.product_id.in_(product_ids))
                        .order_by(VariantModel.sku)
                    )
                )
                .scalars()
                .all()
            )
            grouped: dict[str, list[VariantModel]] = {}
            for variant in variants:
                grouped.setdefault(variant.product_id, []).append(variant)
            return [
                product_to_view(product, grouped.get(product.product_id, []))
                for product in products
            ]
