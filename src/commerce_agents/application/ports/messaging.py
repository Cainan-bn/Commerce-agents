"""Ports de mensageria, outbox e handoff."""

from typing import Protocol

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.events import HandoffRequested


class EventBus(Protocol):
    """Barramento de eventos (Redpanda). A chave de partição é `conversation_id`."""

    async def publish(self, topic: str, key: str, event: StrictModel) -> None: ...


class OutboxRepository(Protocol):
    """Transactional Outbox: grava o evento na mesma transação do estado."""

    async def add(self, topic: str, key: str, event: StrictModel) -> None: ...


class HandoffNotifier(Protocol):
    """Notifica o painel humano (WebSocket)."""

    async def notify(self, request: HandoffRequested) -> None: ...
