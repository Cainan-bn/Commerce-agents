"""Fakes dos ports de canais, ledger e handoff (ADR 0014), em memória."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Literal

from commerce_agents.application.dto.agents import OutboundReply
from commerce_agents.application.dto.channels import HandoffMessage, HandoffRecord, HandoffStatus
from commerce_agents.application.dto.events import HandoffRequested, InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.domain.conversation.conversation import Conversation


class InMemoryInboundLedger:
    """Ledger de mensagens recebidas: claim new/retry/done e complete que grava o outbox."""

    def __init__(self) -> None:
        self._state: dict[str, str] = {}
        self.outbox: list[tuple[str, Any]] = []
        self.completions: list[str] = []

    async def claim(self, event: InboundMessageReceived) -> Literal["new", "retry", "done"]:
        state = self._state.get(event.message_id)
        if state is None:
            self._state[event.message_id] = "claimed"
            return "new"
        if state == "done":
            return "done"
        return "retry"

    async def complete(self, message_id: str, reply: Any, *, at: datetime) -> None:
        self._state[message_id] = "done"
        self.completions.append(message_id)
        if reply is not None:
            self.outbox.append((message_id, reply))

    def status(self, message_id: str) -> str | None:
        return self._state.get(message_id)


class FakeIdentityResolver:
    def __init__(self, customers: dict[tuple[Channel, str], str] | None = None) -> None:
        self._customers = dict(customers or {})
        self.calls: list[tuple[Channel, str]] = []

    async def resolve(self, channel: Channel, external_id: str) -> str | None:
        self.calls.append((channel, external_id))
        return self._customers.get((channel, external_id))


class FakeConversationService:
    """Substitui ConversationService.handle: devolve a resposta configurada ou levanta."""

    def __init__(self, reply: OutboundReply | None = None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[InboundMessageReceived, str]] = []

    async def handle(self, event: InboundMessageReceived, customer_id: str) -> OutboundReply:
        self.calls.append((event, customer_id))
        if self.error is not None:
            raise self.error
        assert self.reply is not None
        return self.reply


class InMemoryHandoffRepository:
    def __init__(self) -> None:
        self.records: dict[str, HandoffRecord] = {}
        self.messages_by_handoff: dict[str, list[HandoffMessage]] = {}

    async def create(self, record: HandoffRecord) -> None:
        self.records[record.handoff_id] = record

    async def get(self, handoff_id: str) -> HandoffRecord | None:
        return self.records.get(handoff_id)

    async def get_active(self, conversation_id: str) -> HandoffRecord | None:
        for record in self.records.values():
            if (
                record.conversation_id == conversation_id
                and record.status is not HandoffStatus.CLOSED
            ):
                return record
        return None

    async def list_active(self) -> Sequence[HandoffRecord]:
        return [r for r in self.records.values() if r.status is not HandoffStatus.CLOSED]

    async def claim(self, handoff_id: str, agent: str, *, at: datetime) -> HandoffRecord | None:
        record = self.records.get(handoff_id)
        if record is None or record.status is not HandoffStatus.OPEN:
            return None
        claimed = replace(record, status=HandoffStatus.CLAIMED, claimed_by=agent)
        self.records[handoff_id] = claimed
        return claimed

    async def close(self, handoff_id: str, *, at: datetime) -> HandoffRecord | None:
        record = self.records.get(handoff_id)
        if record is None or record.status is HandoffStatus.CLOSED:
            return None
        closed = replace(record, status=HandoffStatus.CLOSED, closed_at=at)
        self.records[handoff_id] = closed
        return closed

    async def add_message(self, message: HandoffMessage) -> None:
        self.messages_by_handoff.setdefault(message.handoff_id, []).append(message)

    async def messages(self, handoff_id: str) -> Sequence[HandoffMessage]:
        return list(self.messages_by_handoff.get(handoff_id, []))


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}

    async def get(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def save(self, conversation: Conversation) -> None:
        self.conversations[conversation.conversation_id] = conversation


class CollectingNotifier:
    """HandoffNotifier fake: guarda cada pedido de handoff notificado ao painel."""

    def __init__(self) -> None:
        self.notified: list[HandoffRequested] = []

    async def notify(self, request: HandoffRequested) -> None:
        self.notified.append(request)


class CollectingPanelForwarder:
    """Encaminha mensagens do cliente ao painel durante um handoff ativo."""

    def __init__(self) -> None:
        self.forwarded: list[tuple[str, str]] = []

    async def __call__(self, handoff_id: str, text: str) -> None:
        self.forwarded.append((handoff_id, text))
