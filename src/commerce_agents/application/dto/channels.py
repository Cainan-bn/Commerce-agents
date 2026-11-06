"""Eventos e views dos canais e do handoff (ADR 0014)."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.domain.conversation.channel import Channel

TOPIC_INBOUND = "inbound.messages"
TOPIC_OUTBOUND = "outbound.messages"
TOPIC_HANDOFF = "handoff.events"


def conversation_id_for(channel: Channel, external_id: str) -> str:
    """Uma conversa por usuário e canal."""
    return f"{channel.value}:{external_id}"


class OutboundMessageReady(StrictModel):
    """Mensagem pronta para entrega pelo canal. `message_id` é a chave de idempotência."""

    event_type: Literal["outbound_message_ready"] = "outbound_message_ready"
    message_id: str = Field(min_length=1, description="`reply:<inbound_id>` ou `human:<uuid>`")
    conversation_id: str
    channel: Channel
    recipient_external_id: str
    text: str = Field(min_length=1, max_length=4000)
    citations: tuple[str, ...] = ()
    source: Literal["agent", "human", "system"]
    created_at: datetime


class HandoffStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    CLOSED = "closed"


class HandoffRecord(StrictModel):
    handoff_id: str
    conversation_id: str
    status: HandoffStatus
    reason: str
    priority: Literal["low", "normal", "high", "urgent"]
    summary: str
    created_at: datetime
    claimed_by: str | None = None
    closed_at: datetime | None = None


class HandoffMessage(StrictModel):
    """Mensagem trocada durante o handoff, exibida no painel."""

    handoff_id: str
    author: Literal["customer", "agent_human"]
    text: str
    sent_at: datetime
