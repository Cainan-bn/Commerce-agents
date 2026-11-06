"""Tópicos e (de)serialização dos eventos que trafegam pelo broker."""

import json
from typing import Any, Literal

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.channels import (
    TOPIC_HANDOFF,
    TOPIC_INBOUND,
    TOPIC_OUTBOUND,
    OutboundMessageReady,
)
from commerce_agents.application.dto.events import (
    HandoffRequested,
    InboundMessageReceived,
    IrreversibleActionConfirmed,
    ToolInvoked,
)

__all__ = [
    "TOPIC_HANDOFF",
    "TOPIC_INBOUND",
    "TOPIC_OUTBOUND",
    "PanelCustomerMessage",
    "decode_event",
]


class PanelCustomerMessage(StrictModel):
    """Mensagem do cliente durante um handoff, a caminho do painel (entre processos)."""

    event_type: Literal["panel_customer_message"] = "panel_customer_message"
    handoff_id: str
    text: str


_EVENT_TYPES: dict[str, type[StrictModel]] = {
    model.model_fields["event_type"].default: model
    for model in (
        InboundMessageReceived,
        OutboundMessageReady,
        HandoffRequested,
        ToolInvoked,
        IrreversibleActionConfirmed,
        PanelCustomerMessage,
    )
}


def decode_event(payload: str | bytes) -> StrictModel:
    """JSON -> evento tipado, pelo discriminador `event_type`. Desconhecido levanta ValueError."""
    data: Any = json.loads(payload)
    kind = data.get("event_type") if isinstance(data, dict) else None
    model = _EVENT_TYPES.get(kind) if isinstance(kind, str) else None
    if model is None:
        raise ValueError("event_type desconhecido")
    return model.model_validate_json(payload)
