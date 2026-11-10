"""Miss da demonstração visível e sem handoff falso (ADR 0020, TASK-10-09a).

Contrato fixado (o grafo não sabe de demonstração):
- no miss, `RecordedLLMProvider` devolve uma resposta FINAL válida no protocolo do especialista
  (`parse_agent_action` a lê como `FinalAnswer`) cujo texto é `DEMO_MISS_REPLY`;
- miss no roteador: para ele a resposta é inválida -> `ambiguous` -> agente geral ->
  `clarification()`, sem LLM e sem handoff;
- miss no especialista: o cliente recebe `DEMO_MISS_REPLY`, sem handoff `saida_invalida_do_llm`.
"""

from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.agents.protocol import FinalAnswer, parse_agent_action
from commerce_agents.application.agents.replies import clarification
from commerce_agents.application.dto.views import LLMMessage
from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.graph import CUSTOMER, GraphHarness

pytestmark = pytest.mark.unit


def _empty_cassette(tmp_path: Path) -> Any:
    from commerce_agents.infrastructure.llm.recorded import RecordedLLMProvider

    path = tmp_path / "cassette.jsonl"
    path.write_text("", encoding="utf-8")
    return RecordedLLMProvider(path)


async def test_miss_e_uma_resposta_final_do_protocolo_com_o_aviso(tmp_path: Path):
    from commerce_agents.infrastructure.llm.recorded import DEMO_MISS_REPLY

    result = await _empty_cassette(tmp_path).complete(
        [LLMMessage(role="user", content="fora do roteiro")], max_tokens=64
    )

    action = parse_agent_action(result.content)
    assert isinstance(action, FinalAnswer)
    assert action.text == DEMO_MISS_REPLY


async def test_miss_no_roteador_pede_esclarecimento_sem_handoff(tmp_path: Path):
    from commerce_agents.infrastructure.agents.router import LLMIntentRouter

    provider = _empty_cassette(tmp_path)
    harness = GraphHarness(provider, StoreStub({}), LLMIntentRouter(provider))

    state = await harness.turn("web:demo-miss-1", "mensagem qualquer", message_id="m-miss-1")

    assert state["reply"] == clarification()
    assert state.get("handoff_reason") is None


async def test_miss_no_especialista_mostra_o_aviso_sem_handoff(tmp_path: Path):
    from commerce_agents.infrastructure.llm.recorded import DEMO_MISS_REPLY

    provider = _empty_cassette(tmp_path)
    harness = GraphHarness(provider, StoreStub({"O000001": CUSTOMER}), FakeRouter("order_status"))

    state = await harness.turn(
        "web:demo-miss-2", "onde está meu pedido O000001?", message_id="m-miss-2"
    )

    assert state["reply"] == DEMO_MISS_REPLY
    assert state.get("handoff_reason") is None
