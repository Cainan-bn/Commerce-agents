"""Ports de canais, ledger de mensagens recebidas e handoff (ADR 0014)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from commerce_agents.application.dto.channels import (
    HandoffMessage,
    HandoffRecord,
    OutboundMessageReady,
)
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel


class IdentityResolver(Protocol):
    """Resolve o cliente da loja a partir da identidade autenticada pelo canal."""

    async def resolve(self, channel: Channel, external_id: str) -> str | None:
        """`customer_id` ou `None` (conversa anônima)."""
        ...


class ChannelSender(Protocol):
    """Entrega uma mensagem ao cliente. Idempotente por `message.message_id`."""

    async def send(self, message: OutboundMessageReady) -> None: ...


class InboundLedger(Protocol):
    """Registro de mensagens recebidas: base do efeito exatamente-uma-vez."""

    async def claim(self, event: InboundMessageReceived) -> Literal["new", "retry", "done"]:
        """`new`: primeira vez; `retry`: já recebida mas não concluída; `done`: concluída."""
        ...

    async def complete(
        self, message_id: str, reply: OutboundMessageReady | None, *, at: datetime
    ) -> None:
        """Marca `done` e grava a resposta no outbox na MESMA transação."""
        ...


class OutboxRelay(Protocol):
    """Publica linhas pendentes do outbox no broker. Retorna quantas publicou."""

    async def publish_pending(self, batch_size: int = 100) -> int: ...


class HandoffRepository(Protocol):
    async def create(self, record: HandoffRecord) -> None: ...

    async def get(self, handoff_id: str) -> HandoffRecord | None: ...

    async def get_active(self, conversation_id: str) -> HandoffRecord | None:
        """Handoff `open` ou `claimed` da conversa, se houver."""
        ...

    async def list_active(self) -> Sequence[HandoffRecord]: ...

    async def claim(self, handoff_id: str, agent: str, *, at: datetime) -> HandoffRecord | None:
        """Atômico: só `open` vira `claimed`; `None` se já assumido/fechado."""
        ...

    async def close(self, handoff_id: str, *, at: datetime) -> HandoffRecord | None: ...

    async def add_message(self, message: HandoffMessage) -> None: ...

    async def messages(self, handoff_id: str) -> Sequence[HandoffMessage]: ...
