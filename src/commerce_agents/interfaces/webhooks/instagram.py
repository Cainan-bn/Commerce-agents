"""Normalização do webhook de mensagens do Instagram para `InboundMessageReceived`."""

from datetime import UTC, datetime
from typing import Any

from commerce_agents.application.dto.channels import conversation_id_for
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel

MAX_TEXT = 4000


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_instagram(payload: Any) -> list[InboundMessageReceived]:
    """Só texto recebido; eco, anexos e demais eventos são ignorados. Nunca lança."""
    if not isinstance(payload, dict):
        return []
    events: list[InboundMessageReceived] = []
    for entry in _items(payload.get("entry")):
        for item in _items(entry.get("messaging") if isinstance(entry, dict) else None):
            event = _event(item)
            if event is not None:
                events.append(event)
    return events


def _event(item: Any) -> InboundMessageReceived | None:
    if not isinstance(item, dict):
        return None
    message = item.get("message")
    sender = item.get("sender")
    if not isinstance(message, dict) or not isinstance(sender, dict) or message.get("is_echo"):
        return None
    text, mid, sender_id = message.get("text"), message.get("mid"), sender.get("id")
    if not (isinstance(text, str) and text and isinstance(mid, str) and isinstance(sender_id, str)):
        return None
    try:
        received_at = datetime.fromtimestamp(int(item["timestamp"]) / 1000, tz=UTC)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    return InboundMessageReceived(
        message_id=mid,
        conversation_id=conversation_id_for(Channel.INSTAGRAM, sender_id),
        channel=Channel.INSTAGRAM,
        customer_external_id=sender_id,
        text=text[:MAX_TEXT],
        received_at=received_at,
    )
