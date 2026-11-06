"""Ramos de borda do grafo: roteador quebrado, handoff do agente, ferramenta negada, memória."""

from typing import Any

import pytest

from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.scripted_llm import ScriptedLLM
from tests.unit.agents.test_graph import CONFIG, CONV, CUSTOMER, Harness, _final, _tool, turn_input

pytestmark = pytest.mark.unit


class _BrokenRouter:
    async def route(self, text: str) -> Any:
        raise RuntimeError("roteador fora")


class _MemoryWithPreferences:
    async def get_preferences(self, customer_id: str) -> dict[str, str]:
        return {"tamanho": "M"}

    async def set_preference(self, customer_id: str, key: str, value: str) -> None:
        return None


def _harness(llm: ScriptedLLM, router: Any = None, store: StoreStub | None = None) -> Harness:
    return Harness(llm, router or FakeRouter("order_status"), store or StoreStub({}))


async def test_roteador_quebrado_cai_em_esclarecimento_sem_llm():
    llm = ScriptedLLM([])
    harness = _harness(llm, _BrokenRouter())

    state = await harness.turn("oi")

    assert state["active_agent"] == "geral"
    assert llm.calls == []


async def test_agente_que_pede_handoff_publica_evento_com_o_motivo():
    llm = ScriptedLLM([_tool("request_handoff", {"reason": "cliente irritado", "summary": "x"})])
    harness = _harness(llm)

    state = await harness.turn("isso é um absurdo")

    assert harness.handoffs()[0].reason == "cliente irritado"
    assert state["active_agent"] == "humano"


async def test_ferramenta_fora_da_allowlist_volta_ao_llm_como_not_allowed():
    store = StoreStub({})
    llm = ScriptedLLM([_tool("search_products", {"query": "tênis"}), _final("Não posso.")])
    harness = _harness(llm, store=store)

    await harness.turn("quero um tênis")

    assert store.calls == []
    assert "not_allowed" in " ".join(m.content for m in llm.calls[1])


async def test_cancelamento_com_pedido_invalido_volta_ao_llm_como_erro():
    store = StoreStub({})
    llm = ScriptedLLM([_tool("cancel_order", {"order_id": "xx"}), _final("Qual o número?")])
    harness = _harness(llm, FakeRouter("cancel_order"), store)

    state = await harness.turn("cancela")

    assert state.get("pending_action") is None
    assert "not_found" in " ".join(m.content for m in llm.calls[1])


async def test_preferencias_do_cliente_entram_no_prompt_como_dado():
    llm = ScriptedLLM([_final("Ok.")])
    harness = _harness(llm)
    harness.memory = _MemoryWithPreferences()  # type: ignore[assignment]
    harness.graph = harness._build()

    await harness.graph.ainvoke(turn_input(CONV, CUSTOMER, "oi"), config=CONFIG)

    system = llm.calls[0][0].content
    assert "<dados preferencias>tamanho=M</dados>" in system
