"""Checkpointer Postgres do grafo: a PendingAction sobrevive a reinício e threads são isoladas."""

import json
from typing import Any

import pytest

from tests.fakes.agents import FakeMemory, FakeRouter, StoreStub, key_factory, turn_input
from tests.fakes.clock import FakeClock
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.integration

CUSTOMER = "C0001"


def _tool(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"type": "tool_call", "tool": name, "arguments": arguments})


def _libpq_url(sync_url: str) -> str:
    return sync_url.replace("postgresql+psycopg://", "postgresql://")


def _graph(
    checkpointer: Any,
    *,
    llm: ScriptedLLM,
    store: StoreStub,
    tokens: InMemoryTokenStore,
    clock: FakeClock,
):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.agents.graph import GraphDeps, build_graph

    async def publish(event: Any) -> None:
        return None

    deps = GraphDeps(
        llm=llm,
        router=FakeRouter("cancel_order"),
        tools=store,
        tokens=tokens,
        publish_event=publish,
        clock=clock,
        memory=FakeMemory(),
        new_key=key_factory(),
    )
    return build_graph(deps, checkpointer=checkpointer)


async def test_pending_action_sobrevive_a_reinicio_e_a_confirmacao_executa(
    migration_sync_url: str,
):
    from commerce_agents.infrastructure.agents.checkpointer import create_postgres_checkpointer

    url = _libpq_url(migration_sync_url)
    store = StoreStub({"O000014": CUSTOMER})
    tokens = InMemoryTokenStore()
    clock = FakeClock()
    config = {"configurable": {"thread_id": "conv-restart-1"}}

    # Processo A: propõe o cancelamento e encerra.
    checkpointer_a = create_postgres_checkpointer(url)
    llm_a = ScriptedLLM([_tool("cancel_order", {"order_id": "O000014"})])
    graph_a = _graph(checkpointer_a, llm=llm_a, store=store, tokens=tokens, clock=clock)
    await graph_a.ainvoke(
        turn_input("conv-restart-1", CUSTOMER, "quero cancelar o pedido O000014"), config=config
    )
    assert store.real_calls("cancel_order") == []

    # Processo B (reinício): novo checkpointer e novo grafo no mesmo banco e mesmo thread_id.
    checkpointer_b = create_postgres_checkpointer(url)
    llm_b = ScriptedLLM([])
    graph_b = _graph(checkpointer_b, llm=llm_b, store=store, tokens=tokens, clock=clock)
    state = await graph_b.ainvoke(turn_input("conv-restart-1", CUSTOMER, "sim"), config=config)

    assert len(store.real_calls("cancel_order")) == 1
    assert state["pending_action"] is None


async def test_threads_diferentes_nao_compartilham_pendencia(migration_sync_url: str):
    from commerce_agents.infrastructure.agents.checkpointer import create_postgres_checkpointer

    url = _libpq_url(migration_sync_url)
    store = StoreStub({"O000014": CUSTOMER})
    tokens = InMemoryTokenStore()
    clock = FakeClock()
    checkpointer = create_postgres_checkpointer(url)
    llm = ScriptedLLM([_tool("cancel_order", {"order_id": "O000014"})])
    graph = _graph(checkpointer, llm=llm, store=store, tokens=tokens, clock=clock)

    await graph.ainvoke(
        turn_input("conv-iso-A", CUSTOMER, "quero cancelar o pedido O000014"),
        config={"configurable": {"thread_id": "conv-iso-A"}},
    )
    state_b = await graph.ainvoke(
        turn_input("conv-iso-B", CUSTOMER, "sim"),
        config={"configurable": {"thread_id": "conv-iso-B"}},
    )

    assert store.real_calls("cancel_order") == []
    assert state_b.get("pending_action") is None
