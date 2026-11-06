"""normalize_instagram (ADR 0006): só texto recebido; eco, mídia e status são ignorados."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.domain.conversation.channel import Channel

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "channels"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _normalize(payload: Any) -> list[Any]:
    from commerce_agents.interfaces.webhooks.instagram import normalize_instagram

    return normalize_instagram(payload)


def test_texto_recebido_gera_evento():
    events = _normalize(_load("instagram_text.json"))

    assert len(events) == 1
    event = events[0]
    assert event.message_id == "aWdfZAG.mid.1"
    assert event.customer_external_id == "IGSID-12345"
    assert event.channel is Channel.INSTAGRAM
    assert event.conversation_id == "instagram:IGSID-12345"
    assert event.text == "Quero trocar um tênis"


def test_timestamp_em_milissegundos_vira_datetime_correto():
    events = _normalize(_load("instagram_text.json"))

    assert events[0].received_at == datetime.fromtimestamp(1762430000, tz=UTC)


@pytest.mark.parametrize("fixture", ["instagram_echo.json", "instagram_attachment.json"])
def test_eco_e_anexo_sem_texto_sao_ignorados(fixture: str):
    assert _normalize(_load(fixture)) == []


@pytest.mark.parametrize("payload", [{}, {"entry": None}, "texto-solto", None])
def test_payload_malformado_devolve_lista_vazia(payload: Any):
    assert _normalize(payload) == []
