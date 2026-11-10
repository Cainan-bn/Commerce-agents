"""Traces de um turno pelo grafo (ADR 0018), com fakes de LLM e de ferramentas.

Nomes fixados:
- span raiz `conversation.turn`, sem pai;
- um span filho por nó executado: `graph.node.<nó>` (ex.: `graph.node.supervisor`);
- `llm.complete` por chamada de LLM: `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens` e `gen_ai.provider.name` (o `LLMResult.provider` efetivo);
- `tool.invoke` por ferramenta: `tool.name`, `tool.ok` e, só em erro, `tool.error_code`;
- todos os spans do turno levam `conversation_id`, `channel` e `message_id`.
"""

from typing import Any

import pytest

from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.graph import CUSTOMER, GraphHarness, ProviderLLM, final, tool_call
from tests.fakes.telemetry import ancestors

pytestmark = pytest.mark.unit

CONV = "conv-otel-1"
MESSAGE_ID = "msg-otel-1"


async def _status_turn(store: StoreStub, spans: Any) -> list[Any]:
    llm = ProviderLLM(
        "primario",
        [tool_call("get_order_status", {"order_id": "O000001"}), final("Está a caminho.")],
    )
    harness = GraphHarness(llm, store, FakeRouter("order_status"))

    await harness.turn(CONV, "onde está meu pedido O000001?", message_id=MESSAGE_ID)

    return list(spans.get_finished_spans())


def _root(finished: list[Any]) -> Any:
    roots = [s for s in finished if s.name == "conversation.turn"]
    assert len(roots) == 1
    return roots[0]


async def test_turno_tem_um_span_raiz_com_conversa_canal_e_mensagem(spans: Any):
    finished = await _status_turn(StoreStub({"O000001": CUSTOMER}), spans)

    root = _root(finished)
    assert root.parent is None
    assert root.attributes["conversation_id"] == CONV
    assert root.attributes["channel"] == "web"
    assert root.attributes["message_id"] == MESSAGE_ID
    assert {s.context.trace_id for s in finished} == {root.context.trace_id}


async def test_cada_no_executado_vira_span_filho_da_raiz(spans: Any):
    finished = await _status_turn(StoreStub({"O000001": CUSTOMER}), spans)

    root = _root(finished)
    nodes = [s for s in finished if s.name.startswith("graph.node.")]
    assert {"graph.node.ingest", "graph.node.supervisor", "graph.node.specialist"} <= {
        s.name for s in nodes
    }
    assert all(s.parent is not None and s.parent.span_id == root.context.span_id for s in nodes)


async def test_todo_span_do_turno_leva_conversa_canal_e_mensagem(spans: Any):
    finished = await _status_turn(StoreStub({"O000001": CUSTOMER}), spans)

    assert finished, "o turno deveria ter gerado spans"
    for span in finished:
        assert span.attributes["conversation_id"] == CONV, span.name
        assert span.attributes["channel"] == "web", span.name
        assert span.attributes["message_id"] == MESSAGE_ID, span.name


async def test_cada_chamada_de_llm_tem_span_gen_ai_com_modelo_tokens_e_provider(spans: Any):
    finished = await _status_turn(StoreStub({"O000001": CUSTOMER}), spans)

    root = _root(finished)
    llm_spans = [s for s in finished if s.name == "llm.complete"]
    assert len(llm_spans) == 2
    for span in llm_spans:
        assert span.attributes["gen_ai.request.model"] == "scripted-test"
        assert span.attributes["gen_ai.usage.input_tokens"] == 10
        assert span.attributes["gen_ai.usage.output_tokens"] == 5
        assert span.attributes["gen_ai.provider.name"] == "primario"
        assert root in ancestors(span, finished)


async def test_ferramenta_com_sucesso_tem_span_com_nome_e_ok(spans: Any):
    finished = await _status_turn(StoreStub({"O000001": CUSTOMER}), spans)

    root = _root(finished)
    tool_spans = [s for s in finished if s.name == "tool.invoke"]
    assert len(tool_spans) == 1
    (span,) = tool_spans
    assert span.attributes["tool.name"] == "get_order_status"
    assert span.attributes["tool.ok"] is True
    assert "tool.error_code" not in span.attributes
    assert root in ancestors(span, finished)


async def test_ferramenta_com_erro_tem_span_com_codigo_do_erro(spans: Any):
    finished = await _status_turn(StoreStub({}), spans)

    (span,) = [s for s in finished if s.name == "tool.invoke"]
    assert span.attributes["tool.name"] == "get_order_status"
    assert span.attributes["tool.ok"] is False
    assert span.attributes["tool.error_code"] == "not_found"
