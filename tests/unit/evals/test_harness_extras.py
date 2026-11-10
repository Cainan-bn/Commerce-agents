"""Harness: ramos que os testes do Forja não exercitam (handoff, falha do LLM, custo)."""

import json
from typing import Any

import pytest

from commerce_agents.application.dto.views import LLMResult
from tests.fakes.evals import make_eval_deps
from tests.fakes.traces import scenario

pytestmark = pytest.mark.unit

OWNED = {"customer_id": "C0001"}


def _tool(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"type": "tool_call", "tool": name, "arguments": arguments})


def _final(text: str) -> str:
    return json.dumps({"type": "final", "text": text, "citations": []})


async def _run(scn: Any, deps: Any) -> Any:
    from evals.harness import run_scenario

    return await run_scenario(scn, deps)


async def test_leitura_de_pedido_do_cliente_registra_ok_e_argumentos():
    deps = make_eval_deps([_tool("get_order_status", {"order_id": "O000001"}), _final("ok")])
    scn = scenario(tools=[("get_order_status", {"order_id": "O000001"})])
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    call = trace.tool_calls[0]
    assert (call.ok, call.executed, call.error_code) == (True, True, None)
    assert call.arguments == {"order_id": "O000001"}
    assert [c.model for c in trace.llm_calls] == ["scripted-test"] * 2


async def test_pedido_de_outro_cliente_vira_not_found():
    deps = make_eval_deps([_tool("get_order_status", {"order_id": "O000002"}), _final("x")])
    scn = scenario(tools=[("get_order_status", {"order_id": "O000002"})])
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert (trace.tool_calls[0].ok, trace.tool_calls[0].error_code) == (False, "not_found")


async def test_ferramenta_fora_da_allowlist_conta_como_pedida_e_nao_executada():
    deps = make_eval_deps([_tool("search_products", {"query": "x"}), _final("ok")])
    scn = scenario(forbidden_tools=["search_products"])
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    call = trace.tool_calls[0]
    assert (call.name, call.executed, call.error_code) == ("search_products", False, "not_allowed")


async def test_handoff_pedido_pelo_agente_vira_evento():
    deps = make_eval_deps([_tool("request_handoff", {"reason": "cliente irritado"})])
    scn = scenario(outcome="handoff")
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert trace.handoff_events == ["cliente irritado"]
    assert trace.turns[-1].handoff is True


async def test_falha_do_llm_vira_infra_error():
    deps = make_eval_deps([RuntimeError("provedor caiu")])
    scn = scenario()
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert trace.infra_error and trace.infra_error.startswith("llm")


async def test_confirmacao_so_do_irreversivel_esperado_e_com_token_emitido():
    deps = make_eval_deps([_tool("cancel_order", {"order_id": "O000014"}), _final("feito")])
    scn = scenario(scenario_id="IRR-002", tools=[("cancel_order", {"order_id": "O000014"})])
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert [t.user_text for t in trace.turns][-1] == "sim"
    assert trace.turns[0].awaiting_confirmation is True
    cancel = trace.tool_calls[0]
    assert (cancel.executed, cancel.confirmed, cancel.irreversible) == (True, True, True)
    assert deps.tools.status["O000014"] == "cancelled"


async def test_irreversivel_nao_esperado_nem_proibido_fica_sem_confirmacao():
    deps = make_eval_deps([_tool("cancel_order", {"order_id": "O000014"})])
    scn = scenario(scenario_id="IRR-003")
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert len(trace.turns) == 1
    assert trace.tool_calls[0].executed is False
    assert deps.tools.status["O000014"] == "paid"


async def test_custo_vem_do_cost_usd_de_cada_chamada():
    deps = make_eval_deps([_final("ok")])
    # Acumulador legado do provider é ignorado: o custo vem do `LLMResult.cost_usd`.
    deps.llm.total_cost_usd = 99.0  # type: ignore[attr-defined]
    original = deps.llm.complete

    async def complete(messages: Any, *, max_tokens: int) -> Any:
        result = await original(messages, max_tokens=max_tokens)
        return LLMResult(**result.model_dump(exclude={"cost_usd"}), cost_usd=0.25)

    deps.llm.complete = complete
    scn = scenario()
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert trace.cost_usd == pytest.approx(0.25)


def test_harness_nao_le_mais_o_acumulador_do_provider():
    from pathlib import Path

    import evals.harness

    assert "total_cost_usd" not in Path(evals.harness.__file__).read_text(encoding="utf-8")


async def test_sem_preco_conhecido_o_custo_e_none():
    deps = make_eval_deps([_final("ok")])
    scn = scenario()
    scn.fixtures = OWNED

    trace = await _run(scn, deps)

    assert trace.cost_usd is None
