"""Ports de leitura de dados de negócio. Implementados em `infrastructure/`."""

from typing import Protocol

from commerce_agents.application.dto.views import OrderView, PolicyChunk, ProductView


class OrderRepository(Protocol):
    """Acesso a pedidos."""

    async def get(self, order_id: str) -> OrderView | None:
        """Retorna o pedido ou `None` se não existir."""
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
