"""Roteador sem LLM e instrumentado (adendo do ADR 0017).

Nomes fixados:
- `composition.build_router(llm)` monta o `LLMIntentRouter` sobre o provider instrumentado:
  cada chamada do roteador gera `llm.complete` e conta em `llm.calls` (`outcome=unavailable`
  quando cai); `build_worker` usa `build_router` com o mesmo provider dos agentes;
- queda do roteador vira `handoff.requested{reason=llm_indisponivel}`.
"""

from typing import Any

import pytest

from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.graph import GraphHarness
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.telemetry import collected

pytestmark = pytest.mark.unit

ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",  # pragma: allowlist secret
    "KAFKA_BOOTSTRAP": "broker:9092",
}


class _Named(ScriptedLLM):
    """Provider com `name`, como os elos do breaker (ADR 0017)."""

    def __init__(self, name: str, responses: list[str | Exception]) -> None:
        super().__init__(responses)
        self.name = name


class _DownRouter(FakeRouter):
    async def route(self, text: str) -> Any:
        raise LLMUnavailableError("circuito aberto: primario")


def _soma(points: list[Any], **attributes: str) -> float:
    return sum(
        p.value
        for p in points
        if all(p.attributes.get(key) == value for key, value in attributes.items())
    )


def _build_router(llm: Any) -> Any:
    from commerce_agents.interfaces import composition

    return composition.build_router(llm)


async def test_chamada_do_roteador_gera_span_e_conta_em_llm_calls(spans: Any, metric_reader: Any):
    router = _build_router(_Named("primario", ['{"intent": "order_status", "confidence": 0.9}']))

    decision = await router.route("onde está meu pedido?")

    assert decision.intent == "order_status"
    assert [s.name for s in spans.get_finished_spans()] == ["llm.complete"]
    assert _soma(collected(metric_reader)["llm.calls"], provider="primario", outcome="ok") == 1


async def test_roteador_caido_conta_unavailable_e_propaga(spans: Any, metric_reader: Any):
    router = _build_router(_Named("primario", [LLMUnavailableError("provider respondeu 503")]))

    with pytest.raises(LLMUnavailableError):
        await router.route("onde está meu pedido?")

    (span,) = spans.get_finished_spans()
    assert span.name == "llm.complete"
    assert not span.status.is_ok
    chamadas = collected(metric_reader)["llm.calls"]
    assert _soma(chamadas, provider="primario", outcome="unavailable") == 1


async def test_build_worker_usa_build_router_com_o_provider_dos_agentes(
    monkeypatch: pytest.MonkeyPatch,
):
    from commerce_agents.interfaces import composition

    provider = _Named("primario", [])
    built: list[Any] = []
    original = composition.build_router

    def spy(llm: Any) -> Any:
        built.append(llm)
        return original(llm)

    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(composition, "llm_from_env", lambda env: provider)
    monkeypatch.setattr(composition, "build_router", spy)

    runtime = await composition.build_worker(composition.Settings.from_env(ENV))
    await runtime.close()

    assert built == [provider]


async def test_queda_do_roteador_conta_handoff_por_llm_indisponivel(metric_reader: Any):
    harness = GraphHarness(ScriptedLLM([]), StoreStub({}), _DownRouter("order_status"))

    estado = await harness.turn("conv-rot-met-1", "onde está meu pedido?", message_id="m-rot-1")

    assert estado["handoff_reason"] == "llm_indisponivel"
    handoffs = collected(metric_reader)["handoff.requested"]
    assert _soma(handoffs, reason="llm_indisponivel") == 1
