"""Conversa anônima (customer_id vazio): pedidos e devoluções pedem identificação (ADR 0014)."""

import pytest

from commerce_agents.application.agents.replies import identification_required
from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.scripted_llm import ScriptedLLM
from tests.unit.agents.test_graph import Harness, _final

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "intent",
    ["order_status", "list_orders", "cancel_order", "return_eligibility", "return_request"],
)
async def test_intencoes_de_pedido_recebem_identificacao_sem_llm_nem_ferramentas(intent: str):
    store = StoreStub({})
    llm = ScriptedLLM([])
    harness = Harness(llm, FakeRouter(intent), store)

    state = await harness.turn("meu pedido", customer="")

    assert state["reply"] == identification_required()
    assert llm.calls == []
    assert store.calls == []


async def test_anonimo_ainda_usa_catalogo():
    llm = ScriptedLLM([_final("Temos tênis.")])
    harness = Harness(llm, FakeRouter("product_search"), StoreStub({}))

    state = await harness.turn("tem tênis?", customer="")

    assert state["reply"] == "Temos tênis."


def test_identification_required_e_pt_br_nao_vazio():
    assert "WhatsApp" in identification_required()
