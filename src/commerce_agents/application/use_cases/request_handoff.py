"""Casos de uso do handoff humano: pedir, assumir, responder e encerrar (ADR 0014)."""

import uuid
from collections.abc import Callable
from datetime import datetime

from commerce_agents.application.dto.channels import (
    HandoffMessage,
    HandoffRecord,
    HandoffStatus,
    OutboundMessageReady,
)
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.application.ports.channels import HandoffRepository
from commerce_agents.application.ports.messaging import HandoffNotifier
from commerce_agents.application.ports.repositories import ConversationRepository
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.domain.conversation.conversation import Conversation, ConversationStatus
from commerce_agents.domain.shared.errors import InvalidStateTransition, InvariantViolation

Clock = Callable[[], datetime]


class RequestHandoff:
    def __init__(
        self,
        handoffs: HandoffRepository,
        conversations: ConversationRepository,
        notifier: HandoffNotifier,
        clock: Clock,
        new_id: Callable[[], str],
    ) -> None:
        self._handoffs = handoffs
        self._conversations = conversations
        self._notifier = notifier
        self._clock = clock
        self._new_id = new_id

    async def execute(self, event: HandoffRequested) -> HandoffRecord:
        """Idempotente: com handoff ativo na conversa, devolve o existente sem notificar."""
        if not event.reason:
            raise InvariantViolation("motivo do handoff não pode ser vazio")
        existing = await self._handoffs.get_active(event.conversation_id)
        if existing is not None:
            return existing
        now = self._clock()
        conversation = await self._conversations.get(event.conversation_id) or Conversation(
            conversation_id=event.conversation_id,
            status=ConversationStatus.open,
            messages=(),
            created_at=now,
        )
        record = HandoffRecord(
            handoff_id=self._new_id(),
            conversation_id=event.conversation_id,
            status=HandoffStatus.OPEN,
            reason=event.reason,
            priority=event.priority,
            summary=event.summary,
            created_at=now,
        )
        await self._handoffs.create(record)
        await self._conversations.save(conversation.request_handoff(event.reason, now))
        await self._notifier.notify(event)
        return record


class ClaimHandoff:
    def __init__(self, handoffs: HandoffRepository, *, clock: Clock) -> None:
        self._handoffs = handoffs
        self._clock = clock

    async def execute(self, handoff_id: str, agent: str) -> HandoffRecord | None:
        """Atômico: `None` se já foi assumido, encerrado ou não existe."""
        return await self._handoffs.claim(handoff_id, agent, at=self._clock())


class HumanReply:
    def __init__(self, handoffs: HandoffRepository, *, clock: Clock) -> None:
        self._handoffs = handoffs
        self._clock = clock

    async def execute(self, handoff_id: str, agent: str, text: str) -> OutboundMessageReady:
        record = await self._handoffs.get(handoff_id)
        if record is None:
            raise ValueError("handoff não encontrado")
        if record.status is not HandoffStatus.CLAIMED:
            raise InvalidStateTransition("só é possível responder a um handoff assumido")
        channel, _, external_id = record.conversation_id.partition(":")
        now = self._clock()
        await self._handoffs.add_message(
            HandoffMessage(handoff_id=handoff_id, author="agent_human", text=text, sent_at=now)
        )
        return OutboundMessageReady(
            message_id=f"human:{uuid.uuid4().hex}",
            conversation_id=record.conversation_id,
            channel=Channel(channel),
            recipient_external_id=external_id,
            text=text,
            source="human",
            created_at=now,
        )


class CloseHandoff:
    def __init__(
        self, handoffs: HandoffRepository, conversations: ConversationRepository, *, clock: Clock
    ) -> None:
        self._handoffs = handoffs
        self._conversations = conversations
        self._clock = clock

    async def execute(self, handoff_id: str) -> HandoffRecord | None:
        """Encerra e devolve a conversa ao agente de IA."""
        now = self._clock()
        closed = await self._handoffs.close(handoff_id, at=now)
        if closed is None:
            return None
        conversation = await self._conversations.get(closed.conversation_id)
        if conversation is not None and conversation.status is ConversationStatus.handoff:
            await self._conversations.save(conversation.resume(now))
        return closed
