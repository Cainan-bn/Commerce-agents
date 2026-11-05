"""Eventos que trafegam pelo barramento e pela trilha de auditoria."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.domain.conversation.channel import Channel


class InboundMessageReceived(StrictModel):
    """Mensagem de cliente normalizada. Particionada por `conversation_id`."""

    event_type: Literal["inbound_message_received"] = "inbound_message_received"
    message_id: str = Field(min_length=1, description="Id do canal; chave de deduplicação")
    conversation_id: str = Field(min_length=1)
    channel: Channel
    customer_external_id: str = Field(min_length=1)
    text: str = Field(max_length=4000)
    received_at: datetime


class ToolInvoked(StrictModel):
    """Registro de chamada de ferramenta (auditoria e métricas de tool-calling)."""

    event_type: Literal["tool_invoked"] = "tool_invoked"
    conversation_id: str
    agent: str
    tool_name: str
    arguments: dict[str, str | int | float | bool | None]
    irreversible: bool
    succeeded: bool
    latency_ms: int = Field(ge=0)
    invoked_at: datetime


class HandoffRequested(StrictModel):
    """Pedido de escalonamento para atendente humano."""

    event_type: Literal["handoff_requested"] = "handoff_requested"
    conversation_id: str
    reason: str
    priority: Literal["low", "normal", "high", "urgent"]
    summary: str = Field(description="Resumo estruturado da conversa")
    requested_at: datetime


class IrreversibleActionConfirmed(StrictModel):
    """Confirmação explícita do cliente que consumiu um token de uso único (ADR 0008)."""

    event_type: Literal["irreversible_action_confirmed"] = "irreversible_action_confirmed"
    conversation_id: str
    action: str
    idempotency_key: str
    confirmation_token_id: str
    confirmed_at: datetime
