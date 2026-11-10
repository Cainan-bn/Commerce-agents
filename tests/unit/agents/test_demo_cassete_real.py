"""Regressão da demonstração com o cassete REAL (ADR 0020, diagnóstico da TASK-10-09).

Prova negativa: o cliente C0167 refaz a conversa de cancelamento depois que o O000724 já foi
cancelado. O roteador acerta a msg1 (a chave dele depende só do texto) e o especialista acerta a
1ª chamada, mas a 2ª vê a lista de pedidos mudada e dá miss. A msg2 nunca passou pelo roteador na
gravação (foi ao `confirm`). Contrato: aviso de demonstração e esclarecimento, nunca um anúncio
de handoff sem `HandoffRequested` publicado.
"""

from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from commerce_agents.application.agents.replies import clarification, handoff_notice
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.infrastructure.agents.graph import GraphDeps, build_graph
from commerce_agents.infrastructure.agents.router import LLMIntentRouter
from commerce_agents.infrastructure.llm.recorded import DEMO_MISS_REPLY, RecordedLLMProvider
from tests.fakes.agents import FakeMemory, StoreStub, key_factory, turn_input
from tests.fakes.clock import FakeClock
from tests.fakes.confirmation import InMemoryTokenStore

pytestmark = pytest.mark.unit

CASSETE = Path(__file__).resolve().parents[3] / "data" / "demo" / "cassette.jsonl"
CLIENTE = "C0167"
CONVERSA = "web:demo-sem-reset"
MSG1 = "Quero cancelar o meu pedido que ainda está em processamento."
MSG2 = "Sim, pode cancelar."


class _Turnos:
    """Grafo real com o provider gravado no roteador e no especialista; loja com o O000724
    já cancelado (demo sem reset)."""

    def __init__(self) -> None:
        provider = RecordedLLMProvider(CASSETE)
        store = StoreStub({"O000724": CLIENTE})
        store.status["O000724"] = "cancelled"
        self.published: list[Any] = []

        async def publish(event: Any) -> None:
            self.published.append(event)

        self.graph = build_graph(
            GraphDeps(
                llm=provider,
                router=LLMIntentRouter(provider),
                tools=store,
                tokens=InMemoryTokenStore(),
                publish_event=publish,
                clock=FakeClock(),
                memory=FakeMemory(),
                new_key=key_factory(),
            ),
            checkpointer=MemorySaver(),
        )
        self.budget = 20_000

    async def turn(self, text: str, message_id: str) -> dict[str, Any]:
        state: dict[str, Any] = await self.graph.ainvoke(
            turn_input(CONVERSA, CLIENTE, text, message_id=message_id, budget=self.budget),
            config={"configurable": {"thread_id": CONVERSA}},
        )
        self.budget = state["token_budget_remaining"]
        return state


@pytest.fixture
def turnos() -> _Turnos:
    if not CASSETE.exists():  # pragma: no cover - o cassete é versionado
        pytest.fail(f"cassete da demonstração ausente: {CASSETE}")
    return _Turnos()


async def test_msg1_fora_do_roteiro_mostra_o_aviso_sem_handoff(turnos: _Turnos):
    state = await turnos.turn(MSG1, "m1")

    assert state["intent"] == "cancel_order"  # o roteador acertou o cassete real
    assert state["reply"] == DEMO_MISS_REPLY
    assert state.get("handoff_reason") is None
    assert not state.get("pending_action")


async def test_msg2_confirmacao_sem_proposta_pede_esclarecimento_sem_handoff(turnos: _Turnos):
    await turnos.turn(MSG1, "m1")

    state = await turnos.turn(MSG2, "m2")

    assert state["reply"] == clarification()
    assert state.get("handoff_reason") is None


async def test_nenhum_handoff_anunciado_nem_publicado(turnos: _Turnos):
    replies = [(await turnos.turn(text, f"m{i}"))["reply"] for i, text in enumerate((MSG1, MSG2))]

    assert handoff_notice() not in replies
    assert not [e for e in turnos.published if isinstance(e, HandoffRequested)]
