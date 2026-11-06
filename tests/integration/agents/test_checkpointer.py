"""LazyPostgresSaver: abre sob demanda, cria o schema uma vez e persiste entre instâncias."""

import asyncio
import operator
from typing import Annotated, Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from commerce_agents.infrastructure.agents.checkpointer import create_postgres_checkpointer

pytestmark = pytest.mark.integration


class _State(TypedDict, total=False):
    events: Annotated[list[str], operator.add]


def _graph(checkpointer: Any) -> Any:
    async def step(state: _State) -> _State:
        return {"events": ["passo"]}

    builder = StateGraph(_State)
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=checkpointer)


def _libpq_url(sync_url: str) -> str:
    return sync_url.replace("postgresql+psycopg://", "postgresql://")


async def test_estado_persiste_entre_instancias_do_checkpointer(migration_sync_url: str):
    url = _libpq_url(migration_sync_url)
    config = {"configurable": {"thread_id": "t-persist"}}
    first = create_postgres_checkpointer(url)
    await _graph(first).ainvoke({"events": []}, config=config)
    await first.aclose()

    second = create_postgres_checkpointer(url)
    state = await _graph(second).ainvoke({"events": []}, config=config)
    await second.aclose()

    assert state["events"] == ["passo", "passo"]


async def test_usos_concorrentes_no_primeiro_acesso_inicializam_uma_vez(migration_sync_url: str):
    checkpointer = create_postgres_checkpointer(_libpq_url(migration_sync_url))
    graph = _graph(checkpointer)

    results = await asyncio.gather(
        *(
            graph.ainvoke({"events": []}, config={"configurable": {"thread_id": f"t-{n}"}})
            for n in range(4)
        )
    )
    await checkpointer.aclose()

    assert all(result["events"] == ["passo"] for result in results)
