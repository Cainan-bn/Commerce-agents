"""Helpers para montar Trace e EvalScenario nos testes de avaliação (contrato evals/trace.py)."""

from __future__ import annotations

from typing import Any

from data.eval_scenarios_schema import EvalScenario, Expected, ToolCall

# Imports de evals.trace são preguiçosos: a coleta funciona antes de o módulo existir.


def turn(
    text: str = "oi",
    reply: str = "Olá!",
    *,
    agent: str = "pedidos",
    intent: str = "order_status",
    confidence: float = 0.9,
    awaiting_confirmation: bool = False,
    handoff: bool = False,
) -> Any:
    from evals.trace import TurnRecord

    return TurnRecord(
        user_text=text,
        reply=reply,
        agent=agent,
        intent=intent,
        confidence=confidence,
        awaiting_confirmation=awaiting_confirmation,
        handoff=handoff,
    )


def call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    irreversible: bool = False,
    executed: bool = True,
    confirmed: bool = False,
    ok: bool = True,
    error_code: str | None = None,
) -> Any:
    from evals.trace import ToolCallRecord

    return ToolCallRecord(
        name=name,
        arguments=dict(arguments or {}),
        irreversible=irreversible,
        executed=executed,
        confirmed=confirmed,
        ok=ok,
        error_code=error_code,
        latency_ms=10,
    )


def trace(
    scenario_id: str = "PED-001",
    *,
    turns: list[Any] | None = None,
    tool_calls: list[Any] | None = None,
    handoff_events: list[str] | None = None,
    injection_flagged: bool = False,
    policy_citations: list[str] | None = None,
    retrieved_chunks: list[str] | None = None,
    infra_error: str | None = None,
) -> Any:
    from evals.trace import Trace

    return Trace(
        scenario_id=scenario_id,
        turns=turns or [],
        tool_calls=tool_calls or [],
        llm_calls=[],
        handoff_events=handoff_events or [],
        injection_flagged=injection_flagged,
        policy_citations=policy_citations or [],
        retrieved_chunks=retrieved_chunks or [],
        cost_usd=None,
        infra_error=infra_error,
    )


def scenario(
    *,
    scenario_id: str = "PED-001",
    category: str = "pedidos",
    intent: str = "order_status",
    agent: str = "pedidos",
    tools: list[tuple[str, dict[str, Any]]] | None = None,
    forbidden_tools: list[str] | None = None,
    must_mention: list[str] | None = None,
    outcome: str = "resolved",
    citations_required: bool = False,
    leaks: str | None = None,
) -> EvalScenario:
    return EvalScenario(
        id=scenario_id,
        split="dev",
        category=category,
        persona="cliente de teste",
        goal="objetivo de teste",
        fixtures={},
        turns=["mensagem do cliente"],
        expected=Expected(
            intent=intent,
            agent=agent,
            tools=[ToolCall(name=name, args=args) for name, args in (tools or [])],
            forbidden_tools=forbidden_tools or [],
            irreversible_without_confirmation=False,
            must_mention=must_mention or [],
            outcome=outcome,
            citations_required=citations_required,
            leaks=leaks,
        ),
    )
