"""build_real_deps com roteador injetado: mock_store ASGI, ToolExecutor real e reset da loja."""

import json
from typing import Any

import pytest

from tests.fakes.agents import FakeRouter
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.traces import scenario

pytestmark = pytest.mark.integration


def _tool(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"type": "tool_call", "tool": name, "arguments": arguments})


def _final(text: str) -> str:
    return json.dumps({"type": "final", "text": text, "citations": []})


async def test_cancelamento_confirmado_e_reset_restaura_o_pedido(monkeypatch: pytest.MonkeyPatch):
    from evals.harness import build_real_deps, run_scenario

    monkeypatch.setenv("MOCK_TODAY", "2026-11-01T00:00:00Z")
    llm = ScriptedLLM([_tool("cancel_order", {"order_id": "O000014"}), _final("Cancelado.")])
    deps = build_real_deps(llm=llm, router=FakeRouter("cancel_order"), model="m")
    scn = scenario(scenario_id="IRR-001", tools=[("cancel_order", {"order_id": "O000014"})])
    scn.fixtures = {"customer_id": "C0106"}

    trace = await run_scenario(scn, deps)

    cancel = next(c for c in trace.tool_calls if c.name == "cancel_order")
    assert (cancel.executed, cancel.confirmed, cancel.ok) == (True, True, True)
    assert trace.infra_error is None
    assert "confirmation_token" not in trace.model_dump_json()
    # novo cenário parte do seed de novo: o mesmo cancelamento volta a ser possível
    llm2 = ScriptedLLM([_tool("cancel_order", {"order_id": "O000014"}), _final("Cancelado.")])
    deps2 = build_real_deps(llm=llm2, router=FakeRouter("cancel_order"))
    again = await run_scenario(scn, deps2)
    assert next(c for c in again.tool_calls if c.name == "cancel_order").ok is True
