"""Conversa de atendimento com idempotência e handoff."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from commerce_agents.domain.shared.errors import InvalidStateTransition, InvariantViolation


class ConversationStatus(StrEnum):
    """Estado do ciclo de vida de uma conversa."""

    open = "open"
    handoff = "handoff"
    closed = "closed"


@dataclass(frozen=True)
class Message:
    """Mensagem trocada em uma conversa."""

    message_id: str
    text: str
    sent_at: datetime


@dataclass(frozen=True)
class Conversation:
    """Conversa imutável com histórico ordenado de mensagens."""

    conversation_id: str
    status: ConversationStatus
    messages: tuple[Message, ...]
    created_at: datetime

    def record_inbound(self, message: Message) -> tuple[Conversation, bool]:
        """Registra uma mensagem recebida, ignorando duplicatas por id."""
        if self.status is ConversationStatus.closed:
            raise InvalidStateTransition("conversa fechada não aceita novas mensagens")
        if any(existing.message_id == message.message_id for existing in self.messages):
            return self, False
        return replace(self, messages=self.messages + (message,)), True

    def request_handoff(self, reason: str, at: datetime) -> Conversation:
        """Encaminha a conversa para atendimento humano."""
        if not reason:
            raise InvariantViolation("motivo do handoff não pode ser vazio")
        if self.status is not ConversationStatus.open:
            return self
        return replace(self, status=ConversationStatus.handoff)

    def resume(self, at: datetime) -> Conversation:
        """Devolve a conversa ao agente de IA após o handoff; idempotente em `open`."""
        if self.status is ConversationStatus.closed:
            raise InvalidStateTransition("conversa fechada não pode ser retomada")
        return replace(self, status=ConversationStatus.open)

    def close(self, at: datetime) -> Conversation:
        """Fecha a conversa."""
        return replace(self, status=ConversationStatus.closed)
