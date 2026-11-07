"""run_scenario (ADR 0009/0015): cliente simulado por regra, limites, isolamento e segredos."""

import json

import pytest

from tests.fakes.evals import ExplodingRouter, make_eval_deps
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
