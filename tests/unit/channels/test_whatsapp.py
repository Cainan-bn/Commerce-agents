"""normalize_whatsapp (ADR 0006): payloads reais da Cloud API viram InboundMessageReceived."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "channels"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _normalize(payload: Any) -> list[InboundMessageReceived]:
    from commerce_agents.interfaces.webhooks.whatsapp import normalize_whatsapp

    return normalize_whatsapp(payload)


def test_texto_gera_um_evento_com_campos_corretos():
    events = _normalize(_load("whatsapp_text.json"))

    assert len(events) == 1
    event = events[0]
    assert event.message_id.startswith("wamid.")
    assert event.customer_external_id == "5511900000001"
    assert event.channel is Channel.WHATSAPP
    assert event.conversation_id == "whatsapp:5511900000001"
    assert event.text == "Oi, quero saber onde está meu pedido"
    assert event.received_at == datetime.fromtimestamp(1762430000, tz=UTC)


def test_lote_com_varias_mensagens_gera_um_evento_por_mensagem():
    events = _normalize(_load("whatsapp_batch.json"))

    assert [event.message_id for event in events] == ["wamid.LOTE1", "wamid.LOTE2"]
    assert [event.text for event in events] == ["Primeira", "Segunda"]


@pytest.mark.parametrize(
    "fixture", ["whatsapp_status.json", "whatsapp_reaction.json", "whatsapp_image.json"]
)
def test_status_reacao_e_midia_sem_texto_sao_ignorados(fixture: str):
    assert _normalize(_load(fixture)) == []


@pytest.mark.parametrize(
    "payload", [{}, {"entry": "nao-e-lista"}, {"entry": [{"changes": None}]}, None, 42]
)
def test_payload_vazio_ou_malformado_devolve_lista_vazia(payload: Any):
    assert _normalize(payload) == []


def test_texto_longo_e_truncado_em_4000():
    payload = _load("whatsapp_text.json")
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "a" * 5000

    events = _normalize(payload)

    assert len(events) == 1
    assert len(events[0].text) == 4000
