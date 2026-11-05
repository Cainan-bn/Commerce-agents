"""Testes de fumaça dos contratos públicos."""

import importlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from commerce_agents.application.dto.events import HandoffRequested

CONTRACT_MODULES = [
    "commerce_agents.application.dto.base",
    "commerce_agents.application.dto.events",
    "commerce_agents.application.dto.views",
    "commerce_agents.application.ports.confirmation",
    "commerce_agents.application.ports.llm",
    "commerce_agents.application.ports.messaging",
    "commerce_agents.application.ports.repositories",
    "commerce_agents.domain.conversation.channel",
    "commerce_agents.domain.shared.clock",
    "commerce_agents.domain.shared.ids",
    "commerce_agents.infrastructure.agents.state",
]

VALID_HANDOFF = {
    "conversation_id": "conv-1",
    "reason": "cliente pediu atendimento humano",
    "priority": "high",
    "summary": "Pedido atrasado; cliente quer falar com atendente.",
    "requested_at": datetime(2026, 11, 5, 12, 0, tzinfo=UTC),
}


@pytest.mark.unit
@pytest.mark.parametrize("module_name", CONTRACT_MODULES)
def test_contract_module_imports(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None


@pytest.mark.unit
def test_handoff_requested_accepts_valid_data() -> None:
    event = HandoffRequested(**VALID_HANDOFF)

    assert event.event_type == "handoff_requested"
    assert event.priority == "high"
    assert event.requested_at == VALID_HANDOFF["requested_at"]


@pytest.mark.unit
def test_handoff_requested_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        HandoffRequested(**VALID_HANDOFF, unexpected="não permitido")


@pytest.mark.unit
def test_handoff_requested_is_strict() -> None:
    with pytest.raises(ValidationError):
        HandoffRequested(**{**VALID_HANDOFF, "requested_at": "2026-11-05T12:00:00Z"})
