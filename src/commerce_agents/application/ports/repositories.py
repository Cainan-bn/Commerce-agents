"""Ports de dados de negócio. Implementados em `infrastructure/`."""

from typing import Protocol

from commerce_agents.application.dto.views import OrderView, PolicyChunk, ProductView
from commerce_agents.domain.conversation.conversation import Conversation
from commerce_agents.domain.customer.customer import Customer
from commerce_agents.domain.order.order import Order
from commerce_agents.domain.order.returns import ReturnRequest


class OrderRepository(Protocol):
    """Acesso a pedidos."""

    async def get(self, order_id: str) -> OrderView | None:
        """Retorna o pedido ou `None` se não existir."""
        ...

    async def find(self, order_id: str) -> Order | None:
        """Retorna a entidade de domínio (para regras de negócio) ou `None`."""
        ...

    async def save(self, order: Order) -> None:
        """Insere ou atualiza o pedido e seus itens (upsert por `order_id`)."""
        ...

    async def list_by_customer(self, customer_id: str) -> list[OrderView]:
        """Pedidos do cliente, do mais recente ao mais antigo."""
        ...


class CatalogSearch(Protocol):
    """Busca no catálogo."""

    async def search(self, query: str, limit: int = 5) -> list[ProductView]:
        """Busca híbrida por produtos relevantes à consulta."""
        ...


class PolicyRetriever(Protocol):
    """Recuperação de políticas (RAG híbrido + RRF)."""

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyChunk]:
        """Retorna até `k` trechos com fonte; lista vazia se nada for relevante."""
        ...


class CustomerRepository(Protocol):
    """Acesso a clientes."""

    async def get(self, customer_id: str) -> Customer | None:
        """Retorna o cliente ou `None`."""
        ...

    async def save(self, customer: Customer) -> None:
        """Insere ou atualiza o cliente (upsert por `customer_id`)."""
        ...


class ReturnRequestRepository(Protocol):
    """Solicitações de troca/devolução."""

    async def add(self, request: ReturnRequest) -> None:
        """Registra a solicitação. Idempotente para o mesmo (order_id, sku)."""
        ...

    async def list_for_order(self, order_id: str) -> tuple[ReturnRequest, ...]:
        """Solicitações do pedido, da mais antiga para a mais recente."""
        ...


class ConversationRepository(Protocol):
    """Persistência de conversas e mensagens."""

    async def get(self, conversation_id: str) -> Conversation | None:
        """Retorna a conversa com mensagens em ordem de chegada, ou `None`."""
        ...

    async def save(self, conversation: Conversation) -> None:
        """Insere ou atualiza a conversa. `message_id` é único: reenvio não duplica."""
        ...
