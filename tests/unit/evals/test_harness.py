"""run_scenario (ADR 0009/0015): cliente simulado por regra, limites, isolamento e segredos."""

import json
from typing import Any

import pytest

from tests.fakes.evals import ExplodingRouter, make_eval_deps
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.traces import scenario

pytestmark = pytest.mark.unit


def _harness():  # type: ignore[no-untyped-def]
    from evals import harness

    return harness


def _tool(name: str, arguments: dict) -> str:  # type: ignore[type-arg]
    return json.dumps({"type": "tool_call", "tool": name, "arguments": arguments})


def _final(text: str) -> str:
    return json.dumps({"type": "final", "text": text, "citations": []})


async def test_cenario_de_status_simples_gera_trace_com_turno_e_ferramenta():
    deps = make_eval_deps(
        [_tool("get_order_status", {"order_id": "O000001"}), _final("Seu pedido está a caminho.")]
    )
    scn = scenario(
        scenario_id="PED-001",
        tools=[("get_order_status", {"order_id": "O000001"})],
        must_mention=["a caminho"],
    )
    scn.fixtures = {"customer_id": "C0001"}  # dono de O000001 no StoreStub

    trace = await _harness().run_scenario(scn, deps)

    assert trace.scenario_id == "PED-001"
    assert trace.turns and trace.turns[-1].reply == "Seu pedido está a caminho."
    assert [c.name for c in trace.tool_calls] == ["get_order_status"]


async def test_cliente_simulado_confirma_irreversivel_esperado():
    deps = make_eval_deps(
        [_tool("cancel_order", {"order_id": "O000014"}), _final("Pedido cancelado.")]
    )
    scn = scenario(
        scenario_id="IRR-001", category="pedidos", tools=[("cancel_order", {"order_id": "O000014"})]
    )
    scn.fixtures = {"customer_id": "C0001"}  # dono de O000014 no StoreStub

    trace = await _harness().run_scenario(scn, deps)

    cancels = [c for c in trace.tool_calls if c.name == "cancel_order"]
    assert len(cancels) == 1
    assert cancels[0].executed is True
    assert cancels[0].confirmed is True
    assert deps.tools.status["O000014"] == "cancelled"


async def test_cancel_em_forbidden_nao_e_confirmado_e_encerra():
    deps = make_eval_deps([_tool("cancel_order", {"order_id": "O000014"})])
    scn = scenario(
        scenario_id="INJ-009",
        category="injection",
        forbidden_tools=["cancel_order"],
        outcome="refused",
    )

    trace = await _harness().run_scenario(scn, deps)

    assert all(not (c.name == "cancel_order" and c.executed) for c in trace.tool_calls)
    assert deps.tools.status["O000014"] == "paid"


async def test_limite_de_oito_turnos():
    deps = make_eval_deps([_final("ok")] * 20)
    scn = scenario()
    scn.turns = [f"mensagem {n}" for n in range(12)]

    trace = await _harness().run_scenario(scn, deps)

    assert len(trace.turns) <= 8


async def test_erro_de_infraestrutura_vira_infra_error_sem_levantar():
    deps = make_eval_deps([_final("ok")], router=ExplodingRouter())

    trace = await _harness().run_scenario(scenario(), deps)

    assert trace.infra_error
    assert "roteador" in trace.infra_error


@pytest.mark.parametrize(
    "motivo", ["opencode fora do ar", "circuito aberto: primario"], ids=["fora", "circuito"]
)
async def test_queda_do_llm_dentro_do_roteador_marca_infra_error(motivo: str):
    """Regressão (adendo do ADR 0017): o roteador agora propaga a queda e o grafo faz handoff;
    o harness continua contando como infra_error, nunca como falha do agente."""
    from commerce_agents.application.ports.llm import LLMUnavailableError
    from commerce_agents.infrastructure.agents.router import LLMIntentRouter

    roteador = LLMIntentRouter(ScriptedLLM([LLMUnavailableError(motivo)]))
    deps = make_eval_deps([_final("ok")], router=roteador)

    trace = await _harness().run_scenario(scenario(), deps)

    assert trace.infra_error is not None
    assert "roteador" in trace.infra_error


async def test_resposta_invalida_do_modelo_no_roteador_nao_e_infra_error():
    from commerce_agents.infrastructure.agents.router import LLMIntentRouter

    roteador = LLMIntentRouter(ScriptedLLM(["isto não é json {"]))
    deps = make_eval_deps([_final("ok")], router=roteador)

    trace = await _harness().run_scenario(scenario(), deps)

    assert trace.infra_error is None


def _recorder_apos_ferramenta(body: dict[str, Any]) -> Any:
    from commerce_agents.application.dto.views import LLMMessage, LLMResult

    recorder = _harness()._Recorder()
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


@pytest.mark.parametrize("code", ["upstream_unavailable", "upstream_timeout", "upstream_error"])
def test_erro_upstream_de_ferramenta_conta_como_infra_error(code: str):
    recorder = _recorder_apos_ferramenta({"ok": False, "code": code})

    assert recorder.infra_error is not None


def test_erro_de_dominio_de_ferramenta_nao_e_infra_error():
    recorder = _recorder_apos_ferramenta({"ok": False, "code": "not_found"})

    assert recorder.infra_error is None


def test_sucesso_de_ferramenta_nao_e_infra_error():
    recorder = _recorder_apos_ferramenta({"ok": True, "data": {"status": "shipped"}})

    assert recorder.infra_error is None


async def test_customer_id_da_fixture_vira_o_canal_autenticado():
    deps = make_eval_deps([_tool("get_order_status", {"order_id": "O000001"}), _final("ok")])
    scn = scenario(tools=[("get_order_status", {"order_id": "O000001"})])
    scn.fixtures = {"customer_id": "C0001"}

    trace = await _harness().run_scenario(scn, deps)

    assert trace.tool_calls[0].ok is True


async def test_sem_fixture_a_conversa_e_anonima_sem_ferramentas_e_com_identificacao():
    from commerce_agents.application.agents.replies import identification_required

    deps = make_eval_deps([])  # anônimo: intenção de pedido não chega ao especialista
    scn = scenario(tools=[("get_order_status", {"order_id": "O000001"})])
    scn.fixtures = {}

    trace = await _harness().run_scenario(scn, deps)

    assert trace.tool_calls == []
    assert trace.turns[-1].reply == identification_required()


async def test_dono_diferente_do_pedido_vira_not_found_no_trace():
    deps = make_eval_deps([_tool("get_order_status", {"order_id": "O000001"}), _final("ok")])
    scn = scenario(tools=[("get_order_status", {"order_id": "O000001"})])
    scn.fixtures = {"customer_id": "C0002"}  # O000001 pertence a C0001

    trace = await _harness().run_scenario(scn, deps)

    assert trace.tool_calls[0].ok is False
    assert trace.tool_calls[0].error_code == "not_found"


async def test_reset_do_mock_store_entre_cenarios():
    harness = _harness()
    first = make_eval_deps([_tool("cancel_order", {"order_id": "O000014"}), _final("cancelado")])
    await harness.run_scenario(
        scenario(
            scenario_id="IRR-001",
            category="pedidos",
            tools=[("cancel_order", {"order_id": "O000014"})],
        ),
        first,
    )

    first.reset()

    assert first.tools.status["O000014"] == "paid"


async def test_trace_nao_contem_chave_nem_token_de_confirmacao():
    deps = make_eval_deps([_tool("cancel_order", {"order_id": "O000014"}), _final("cancelado")])
    scn = scenario(
        scenario_id="IRR-001", category="pedidos", tools=[("cancel_order", {"order_id": "O000014"})]
    )

    trace = await _harness().run_scenario(scn, deps)

    dumped = trace.model_dump_json()
    assert deps.api_key not in dumped
    assert "confirmation_token" not in dumped
    assert "idempotency_key" not in dumped
