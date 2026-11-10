"""Caos no grafo (ADR 0017, metas de Sistema da Fase 09), com fakes e relógio falso.

- Provider sempre caído atrás do circuit breaker: a primeira conversa degrada para humano
  (`llm_indisponivel`) e a segunda nem chega ao provider (circuito aberto), sem gastar tempo.
- Loja devolvendo 503 ou estourando o timeout em `get_order_status`: o erro chega ao LLM como
  resultado de ferramenta, nenhuma ação irreversível é feita e nenhuma exceção vaza.
"""

from typing import Any

import httpx
import pytest

from commerce_agents.application.agents.replies import llm_unavailable
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.agents import FakeMemory, FakeRouter, StoreStub, key_factory, turn_input
from tests.fakes.clock import FakeClock, FakeMonotonic
from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore
from tests.fakes.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.unit

CUSTOMER = "C0001"
PROVIDER_TIMEOUT_S = 30.0


class DownProvider:
    """Provider caído: cada chamada consome o timeout inteiro no relógio falso e falha."""

    def __init__(self, clock: FakeMonotonic) -> None:
        self.clock = clock
        self.calls = 0

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        self.calls += 1
        self.clock.advance(PROVIDER_TIMEOUT_S)
        raise LLMUnavailableError("timeout do provider")


def _graph(llm: Any, tools: Any, published: list[Any]) -> Any:
    from langgraph.checkpoint.memory import MemorySaver

    from commerce_agents.infrastructure.agents.graph import GraphDeps, build_graph

    async def publish(event: Any) -> None:
        published.append(event)

    deps = GraphDeps(
        llm=llm,
        router=FakeRouter("order_status"),
        tools=tools,
        tokens=InMemoryTokenStore(),
        publish_event=publish,
        clock=FakeClock(),
        memory=FakeMemory(),
        new_key=key_factory(),
    )
    return build_graph(deps, checkpointer=MemorySaver())


async def _turn(graph: Any, conversation_id: str, text: str) -> dict[str, Any]:
    state: dict[str, Any] = await graph.ainvoke(
        turn_input(conversation_id, CUSTOMER, text),
        config={"configurable": {"thread_id": conversation_id}},
    )
    return state


def _handoffs(published: list[Any]) -> list[HandoffRequested]:
    return [event for event in published if isinstance(event, HandoffRequested)]


# ---------------------------------------------------------------- provider sempre caído


async def test_provider_caido_primeira_conversa_faz_handoff_e_a_segunda_nao_chama_o_provider():
    from commerce_agents.infrastructure.llm.resilience import CircuitBreakerLLM

    clock = FakeMonotonic()
    inner = DownProvider(clock)
    llm = CircuitBreakerLLM(
        inner, name="primario", failure_threshold=1, window_s=60, open_s=30, clock=clock
    )
    published: list[Any] = []
    graph = _graph(llm, StoreStub({}), published)

    primeira = await _turn(graph, "conv-caos-1", "onde está meu pedido?")

    assert primeira["reply"] == llm_unavailable()
    assert [h.reason for h in _handoffs(published)] == ["llm_indisponivel"]
    assert inner.calls == 1

    inicio = clock()
    segunda = await _turn(graph, "conv-caos-2", "e o meu pedido?")
    gasto = clock() - inicio

    assert inner.calls == 1
    assert gasto < 0.05
    assert segunda["reply"] == llm_unavailable()
    assert [h.reason for h in _handoffs(published)] == ["llm_indisponivel"] * 2


# ------------------------------------------------------------------- loja fora do ar


def _store_503(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"detail": "loja fora do ar"}, request=request)


def _store_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timeout simulado", request=request)


@pytest.mark.parametrize(
    ("handler", "code"),
    [(_store_503, "upstream_unavailable"), (_store_timeout, "upstream_timeout")],
    ids=["503", "timeout"],
)
async def test_loja_fora_do_ar_vira_erro_upstream_sem_acao_irreversivel_nem_excecao(
    handler: Any, code: str
):
    from commerce_agents.infrastructure.mcp.executor import ToolExecutor

    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    async def no_sleep(_: float) -> None:
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording), base_url="http://store")
    executor = ToolExecutor(
        client=client,
        tokens=InMemoryTokenStore(),
        idempotency=InMemoryIdempotencyRegistry(),
        sleep=no_sleep,
    )
    llm = ScriptedLLM(
        [
            '{"type": "tool_call", "tool": "get_order_status",'
            ' "arguments": {"order_id": "O000001"}}',
            '{"type": "final", "text": "A loja está fora do ar agora; tente de novo em'
            ' instantes.", "citations": []}',
        ]
    )
    published: list[Any] = []
    graph = _graph(llm, executor, published)

    state = await _turn(graph, "conv-caos-loja", "onde está meu pedido O000001?")

    assert state["reply"] == "A loja está fora do ar agora; tente de novo em instantes."
    assert requests, "a loja deveria ter sido consultada"
    assert {request.method for request in requests} == {"GET"}
    assert all("cancel" not in request.url.path for request in requests)
    resultado_da_ferramenta = "\n".join(m.content for m in llm.calls[-1])
    assert code in resultado_da_ferramenta
    await client.aclose()
