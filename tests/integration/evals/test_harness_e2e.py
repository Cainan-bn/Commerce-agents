"""Harness ponta a ponta: grafo real, ToolExecutor e mock_store ASGI, cancelamento confirmado."""

import json
from typing import Any

import pytest

from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.traces import scenario

pytestmark = pytest.mark.integration


async def test_cancelamento_confirmado_pelo_cliente_simulado_com_mock_store(
    monkeypatch: pytest.MonkeyPatch,
):
    from evals.harness import EvalDeps, run_scenario  # noqa: F401 - contrato do CORE

    monkeypatch.setenv("MOCK_TODAY", "2026-11-01T00:00:00Z")
    llm = ScriptedLLM(
        [
            json.dumps(
                {"type": "tool_call", "tool": "cancel_order", "arguments": {"order_id": "O000014"}}
            ),
            json.dumps({"type": "final", "text": "Pedido cancelado.", "citations": []}),
        ]
    )
    deps: Any = _real_deps(llm)
    scn = scenario(
        scenario_id="IRR-001", category="pedidos", tools=[("cancel_order", {"order_id": "O000014"})]
    )
    scn.fixtures = {"customer_id": "C0001"}

    trace = await run_scenario(scn, deps)

    cancels = [c for c in trace.tool_calls if c.name == "cancel_order"]
    assert cancels and cancels[0].confirmed is True
    assert trace.infra_error is None


def _real_deps(llm: ScriptedLLM) -> Any:
    """Monta EvalDeps com ToolExecutor real sobre o mock_store ASGI (fábrica do CORE)."""
    from evals.harness import build_real_deps  # noqa: F401 - contrato do CORE

    return build_real_deps(llm=llm)
