"""Normalização do webhook da WhatsApp Cloud API para `InboundMessageReceived`."""

from datetime import UTC, datetime
from typing import Any

from commerce_agents.application.dto.channels import conversation_id_for
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel

MAX_TEXT = 4000


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_whatsapp(payload: Any) -> list[InboundMessageReceived]:
    """Só mensagens de texto; status, reações e mídia são ignorados. Nunca lança."""
    if not isinstance(payload, dict):
        return []
    events: list[InboundMessageReceived] = []
    for entry in _items(payload.get("entry")):
        for change in _items(entry.get("changes") if isinstance(entry, dict) else None):
            value = change.get("value") if isinstance(change, dict) else None
            for message in _items(value.get("messages") if isinstance(value, dict) else None):
                event = _event(message)
                if event is not None:
                    events.append(event)
    return events


def _event(message: Any) -> InboundMessageReceived | None:
    if not isinstance(message, dict) or message.get("type") != "text":
        return None
    body = message.get("text")
    text = body.get("body") if isinstance(body, dict) else None
    sender = "".join(ch for ch in str(message.get("from", "")) if ch.isdigit())
    message_id = message.get("id")
    if not (isinstance(text, str) and text and sender and isinstance(message_id, str)):
        return None
    try:
        received_at = datetime.fromtimestamp(int(message["timestamp"]), tz=UTC)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    return InboundMessageReceived(
        message_id=message_id,
        conversation_id=conversation_id_for(Channel.WHATSAPP, sender),
        channel=Channel.WHATSAPP,
        customer_external_id=sender,
        text=text[:MAX_TEXT],
        received_at=received_at,
    )
