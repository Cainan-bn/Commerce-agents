"""Itens malformados dentro de payloads válidos dos webhooks são descartados sem lançar."""

from typing import Any

import pytest

from commerce_agents.interfaces.webhooks.instagram import normalize_instagram
from commerce_agents.interfaces.webhooks.whatsapp import normalize_whatsapp

pytestmark = pytest.mark.unit


def _wa(message: Any) -> dict[str, Any]:
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


def _ig(item: Any) -> dict[str, Any]:
    return {"entry": [{"messaging": [item]}]}


@pytest.mark.parametrize(
    "message",
    [
        "texto",
        {"type": "text", "from": "55", "id": "w1", "timestamp": "abc", "text": {"body": "oi"}},
        {"type": "text", "from": "55", "id": "w1", "text": {"body": "oi"}},
        {"type": "text", "from": "", "id": "w1", "timestamp": "1", "text": {"body": "oi"}},
        {"type": "text", "from": "55", "id": "w1", "timestamp": "1", "text": "oi"},
    ],
)
def test_whatsapp_item_malformado_e_ignorado(message: Any):
    assert normalize_whatsapp(_wa(message)) == []


@pytest.mark.parametrize(
    "item",
    [
        "texto",
        {"sender": {"id": "I"}, "message": {"mid": "m", "text": "oi"}},
        {"sender": {"id": "I"}, "timestamp": "x", "message": {"mid": "m", "text": "oi"}},
        {"sender": "I", "timestamp": 1, "message": {"mid": "m", "text": "oi"}},
        {"sender": {"id": "I"}, "timestamp": 1, "message": {"mid": 1, "text": "oi"}},
    ],
)
def test_instagram_item_malformado_e_ignorado(item: Any):
    assert normalize_instagram(_ig(item)) == []
