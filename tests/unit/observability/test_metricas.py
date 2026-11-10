"""Métricas OTel do atendimento (ADR 0018), lidas do InMemoryMetricReader em temporalidade delta.

Nomes fixados:
- `conversation.turn.duration`: histograma da latência do turno, em segundos;
- `llm.calls`: contador com `provider` e `outcome` ("ok" ou "unavailable");
- `handoff.requested`: contador com `reason`;
- `llm.circuit.opened`: contador com `provider` (o `name` do CircuitBreakerLLM).
"""

from typing import Any

import pytest

from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.clock import FakeMonotonic
from tests.fakes.graph import GraphHarness, ProviderLLM, final
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.telemetry import collected

pytestmark = pytest.mark.unit


def _soma(points: list[Any], **attributes: str) -> float:
    return sum(
        p.value
        for p in points
        if all(p.attributes.get(key) == value for key, value in attributes.items())
    )


async def _dois_turnos(metric_reader: Any) -> dict[str, list[Any]]:
    llm = ProviderLLM(
        "primario", [final("Está a caminho."), LLMUnavailableError("provider fora do ar")]
    )
    harness = GraphHarness(llm, StoreStub({}), FakeRouter("order_status"))

    await harness.turn("conv-met-1", "onde está meu pedido?", message_id="msg-met-1")
    await harness.turn("conv-met-2", "e o meu pedido?", message_id="msg-met-2")

    return collected(metric_reader)


async def test_histograma_de_latencia_do_turno_tem_um_ponto_por_turno(metric_reader: Any):
    metricas = await _dois_turnos(metric_reader)

    assert sum(p.count for p in metricas["conversation.turn.duration"]) == 2


async def test_contador_de_chamadas_de_llm_por_provider_e_resultado(metric_reader: Any):
    metricas = await _dois_turnos(metric_reader)

    chamadas = metricas["llm.calls"]
    assert _soma(chamadas, provider="primario", outcome="ok") == 1
    assert _soma(chamadas, outcome="unavailable") == 1


async def test_contador_de_handoff_por_motivo(metric_reader: Any):
    metricas = await _dois_turnos(metric_reader)

    assert _soma(metricas["handoff.requested"], reason="llm_indisponivel") == 1


async def test_contador_de_aberturas_do_circuito(metric_reader: Any):
    from commerce_agents.infrastructure.llm.resilience import CircuitBreakerLLM

    breaker = CircuitBreakerLLM(
        ScriptedLLM([LLMUnavailableError("fora do ar")]),
        name="primario",
        failure_threshold=1,
        window_s=60,
        open_s=30,
        clock=FakeMonotonic(),
    )
    for _ in range(3):
        with pytest.raises(LLMUnavailableError):
            await breaker.complete([], max_tokens=8)

    metricas = collected(metric_reader)

    assert _soma(metricas["llm.circuit.opened"], provider="primario") == 1
