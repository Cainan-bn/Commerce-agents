"""Contexto de trace pelo broker (ADR 0018): quem publica injeta, quem consome continua o trace.

O producer e o consumer do aiokafka são trocados por fakes. Contrato fixado: `KafkaEventBus`
passa `headers=[("traceparent", b"...")]` (formato W3C) ao `send_and_wait`, e `consume` roda o
handler num span cujo pai vem dos headers do registro.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from commerce_agents.application.dto.events import HandoffRequested
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit

TOPIC = "conversations.handoff"
SENT: list[list[dict[str, Any]]] = []


class FakeProducer:
    def __init__(self, **_: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        SENT.append(self.sent)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_and_wait(
        self,
        topic: str,
        value: bytes | None = None,
        key: bytes | None = None,
        headers: list[tuple[str, bytes]] | None = None,
        **_: Any,
    ) -> None:
        self.sent.append({"topic": topic, "value": value, "key": key, "headers": headers})


def _consumer_with(records: list[Any]) -> type:
    class FakeConsumer:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.commits = 0

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def commit(self) -> None:
            self.commits += 1

        def seek(self, *_: Any) -> None:
            return None

        def __aiter__(self) -> Any:
            return self._records()

        async def _records(self) -> Any:
            for record in records:
                yield record

    return FakeConsumer


def _event() -> HandoffRequested:
    return HandoffRequested(
        conversation_id="conv-prop-1",
        reason="llm_indisponivel",
        priority="normal",
        summary="resumo",
        requested_at=BASE_TIME,
    )


def _header(headers: list[tuple[str, Any]] | None, name: str) -> str:
    for key, value in headers or []:
        if key == name:
            return value.decode() if isinstance(value, bytes) else str(value)
    raise AssertionError(f"header {name!r} ausente em {headers!r}")


async def _publish_inside_span(monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict[str, Any]]:
    from opentelemetry import trace

    from commerce_agents.infrastructure.messaging import bus

    SENT.clear()
    monkeypatch.setattr(bus, "AIOKafkaProducer", FakeProducer)
    tracer = trace.get_tracer("tests.observability")
    with tracer.start_as_current_span("webhook") as span:
        await bus.KafkaEventBus("fake:9092").publish(TOPIC, "conv-prop-1", _event())
        trace_id = span.get_span_context().trace_id
    ((message,),) = SENT
    return trace_id, message


async def test_publicar_injeta_traceparent_do_span_corrente(
    spans: Any, monkeypatch: pytest.MonkeyPatch
):
    trace_id, message = await _publish_inside_span(monkeypatch)

    traceparent = _header(message["headers"], "traceparent")
    assert traceparent.split("-")[1] == f"{trace_id:032x}"


async def test_consumidor_continua_o_mesmo_trace_id(spans: Any, monkeypatch: pytest.MonkeyPatch):
    from opentelemetry import trace

    from commerce_agents.infrastructure.messaging import bus

    trace_id, message = await _publish_inside_span(monkeypatch)
    record = SimpleNamespace(
        topic=TOPIC,
        partition=0,
        offset=0,
        key=message["key"],
        value=message["value"],
        headers=message["headers"],
    )
    monkeypatch.setattr(bus, "AIOKafkaConsumer", _consumer_with([record]))
    vistos: list[int] = []

    async def handler(event: Any) -> None:
        assert isinstance(event, HandoffRequested)
        vistos.append(trace.get_current_span().get_span_context().trace_id)

    await bus.consume("fake:9092", TOPIC, "grupo", handler)

    assert vistos == [trace_id]
