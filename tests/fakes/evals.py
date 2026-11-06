"""Fakes do harness de avaliação: EvalDeps com LLM roteirizado, roteador e loja fake."""

from __future__ import annotations

import itertools
from typing import Any

from tests.fakes.agents import FakeMemory, FakeRouter, StoreStub
from tests.fakes.clock import FakeClock
from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore
from tests.fakes.scripted_llm import ScriptedLLM


class Recorder:
    """Coleta eventos publicados pelo grafo."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


class ExplodingRouter:
    """Roteador que levanta: simula falha de infraestrutura fora do grafo."""

    async def route(self, text: str) -> Any:
        raise RuntimeError("roteador indisponível")


def make_eval_deps(
    llm_responses: list[str | Exception],
    *,
    intent: str = "order_status",
    confidence: float = 0.9,
    store: StoreStub | None = None,
    router: Any = None,
) -> Any:
    """Monta EvalDeps com fakes. A loja é um StoreStub com pedidos do seed usados nos testes."""
    from evals.harness import EvalDeps

    from commerce_agents.infrastructure.agents.graph import GraphDeps  # noqa: F401 - contrato

    store = store or StoreStub({"O000001": "C0001", "O000014": "C0001", "O000002": "C0002"})
    llm = ScriptedLLM(llm_responses)
    recorder = Recorder()
    ids = itertools.count(1)

    def reset() -> None:
        store.status = {order_id: "paid" for order_id in store.owners}
        store.calls.clear()

    return EvalDeps(
        llm=llm,
        router=router or FakeRouter(intent, confidence),
        tools=store,
        tokens=InMemoryTokenStore(),
        idempotency=InMemoryIdempotencyRegistry(),
        publish=recorder,
        clock=FakeClock(),
        memory=FakeMemory(),
        new_key=lambda: f"idem-eval-{next(ids):06d}",
        reset=reset,
        model="modelo-de-teste",
        temperature=0.0,
        llm_provider_name="scripted",
        api_key="sk-chave-de-teste-nao-vazar-000",  # pragma: allowlist secret
    )
