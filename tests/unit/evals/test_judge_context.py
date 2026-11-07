"""Contexto do juiz: resultado das ferramentas e identificação do cliente no trace e no prompt."""

import json
from typing import Any

import pytest

from tests.fakes.evals import make_eval_deps
from tests.fakes.traces import call, scenario, trace, turn

pytestmark = pytest.mark.unit


def _final(text: str) -> str:
    return json.dumps({"type": "final", "text": text})


def _tool(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"type": "tool_call", "tool": name, "arguments": arguments})


def _recorder_apos(body: dict[str, Any]) -> Any:
    from evals import harness

    from commerce_agents.application.dto.views import LLMMessage, LLMResult

    recorder = harness._Recorder()
    pedido = LLMResult(
        content=_tool("get_order_status", {"order_id": "O000001"}),
        model="m",
        input_tokens=1,
        output_tokens=1,
    )
    recorder.on_llm_result(pedido, latency_ms=1)
    resultado = "<dados ferramenta>" + json.dumps(body) + "</dados>"
    recorder.on_llm_request([LLMMessage(role="user", content=resultado)])
    return recorder


# ----------------------------------------------------------------- trace


def test_result_excerpt_e_json_compacto_do_resultado():
    recorder = _recorder_apos({"ok": True, "data": {"status": "shipped"}})

    assert recorder.tool_calls[0].result_excerpt == '{"ok":true,"data":{"status":"shipped"}}'


def test_result_excerpt_e_truncado_a_600_caracteres():
    recorder = _recorder_apos({"ok": True, "data": {"texto": "x" * 2000}})

    assert len(recorder.tool_calls[0].result_excerpt) == 600


def test_result_excerpt_nao_traz_campos_ocultos():
    recorder = _recorder_apos(
        {
            "ok": True,
            "data": {
                "status": "ok",
                "confirmation_token": "SEGREDO",
                "api_key": "SEGREDO2",  # pragma: allowlist secret
            },  # pragma: allowlist secret,
        }
    )

    excerpt = recorder.tool_calls[0].result_excerpt
    assert "SEGREDO" not in excerpt
    assert "status" in excerpt


def test_irreversivel_nao_executada_tem_excerpt_vazio():
    from evals import harness

    from commerce_agents.application.dto.views import LLMResult

    recorder = harness._Recorder()
    cancelar = LLMResult(
        content=_tool("cancel_order", {"order_id": "O000001"}),
        model="m",
        input_tokens=1,
        output_tokens=1,
    )
    recorder.on_llm_result(cancelar, latency_ms=1)

    assert recorder.tool_calls[0].result_excerpt == ""


def test_trace_tem_defaults_compativeis():
    tr = trace()

    assert tr.customer_identified is False
    assert call("x").result_excerpt == ""


@pytest.mark.parametrize(("fixtures", "esperado"), [({"customer_id": "C0001"}, True), ({}, False)])
async def test_harness_preenche_customer_identified(fixtures: dict[str, str], esperado: bool):
    from evals import harness

    deps = make_eval_deps([_final("ok")])
    scn = scenario()
    scn.fixtures = fixtures

    tr = await harness.run_scenario(scn, deps)

    assert tr.customer_identified is esperado


def test_linha_antiga_do_jsonl_sem_os_campos_ainda_carrega():
    from evals.calibration import trace_from_row

    row = {
        "id": "PED-001",
        "turns": [{"user_text": "oi", "reply": "olá", "agent": "pedidos", "intent": "x"}],
        "tool_calls": [{"name": "get_order_status", "ok": True, "error_code": None}],
        "policy_citations": [],
    }

    tr = trace_from_row(row)

    assert tr.customer_identified is False
    assert tr.tool_calls[0].result_excerpt == ""


def test_jsonl_serializa_excerpt_e_identificacao_e_trace_from_row_le():
    from evals.calibration import trace_from_row
    from evals.report import build_trace_rows

    scn = scenario()
    tr = trace(
        turns=[turn()],
        tool_calls=[call("get_order_status", result_excerpt='{"ok":true}')],
    )
    tr.customer_identified = True

    row = build_trace_rows({scn.id: scn}, {scn.id: tr})[0]
    back = trace_from_row(row)

    assert row["customer_identified"] is True
    assert row["tool_calls"][0]["result_excerpt"] == '{"ok":true}'
    assert back.customer_identified is True
    assert back.tool_calls[0].result_excerpt == '{"ok":true}'
