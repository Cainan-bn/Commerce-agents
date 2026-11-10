"""Contexto de trace pelo outbox (adendo do ADR 0017, refina o ADR 0018), com Postgres real.

Nomes fixados:
- coluna `outbox.traceparent` (texto, nullable; migração nova): o `traceparent` W3C do contexto
  corrente quando a linha é gravada (`SqlInboundLedger.complete` e `SqlOutboxRepository.add`);
  sem contexto ativo, NULL;
- `SqlOutboxRelay.publish_pending` publica cada linha dentro de um span `outbox.publish` filho do
  `traceparent` DA LINHA (nunca o contexto do laço do relay); linha sem `traceparent` publica sem
  header de trace e sem erro;
- ponta a ponta: turno -> outbox -> relay -> consumidor de `outbound.messages` -> `channel.send`
  formam um único trace_id, e `channel.send` leva `conversation_id`.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy
from sqlalchemy import inspect, text

from commerce_agents.application.dto.channels import TOPIC_OUTBOUND, OutboundMessageReady
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.persistence.migrate import upgrade_to_head
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _reply(n: int, conversation_id: str = "whatsapp:5511900000001") -> OutboundMessageReady:
    return OutboundMessageReady(
        message_id=f"reply:wamid.T{n}",
        conversation_id=conversation_id,
        channel=Channel.WHATSAPP,
        recipient_external_id="5511900000001",
        text=f"resposta {n}",
        source="agent",
        created_at=AT,
    )


def _inbound(n: int) -> InboundMessageReceived:
    return InboundMessageReceived(
        message_id=f"wamid.T{n}",
        conversation_id="whatsapp:5511900000001",
        channel=Channel.WHATSAPP,
        customer_external_id="5511900000001",
        text="onde está meu pedido?",
        received_at=AT,
    )


class HeaderBus:
    """Bus fake que guarda os headers que o KafkaEventBus mandaria (contexto corrente)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, Any, dict[str, str]]] = []

    async def publish(self, topic: str, key: str, event: Any) -> None:
        from commerce_agents.infrastructure.telemetry import inject_headers

        headers = {name: value.decode() for name, value in inject_headers()}
        self.published.append((topic, event, headers))


class SpySender:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, message: Any) -> None:
        self.sent.append(message)


def _tracer() -> Any:
    from opentelemetry import trace

    return trace.get_tracer("teste-outbox")


def _traceparent(span: Any) -> str:
    context = span.get_span_context()
    return f"00-{context.trace_id:032x}-{context.span_id:016x}-01"


async def _stored_traceparents(engine: Any) -> list[str | None]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT traceparent FROM outbox ORDER BY id"))
        return [row.traceparent for row in rows]


def _relay(factory: Any, bus: Any) -> Any:
    from commerce_agents.infrastructure.persistence.outbox import SqlOutboxRelay

    return SqlOutboxRelay(factory, bus)


# ------------------------------------------------------------------ 5. gravação


def test_migracao_cria_coluna_traceparent_nullable(migration_sync_url: str) -> None:
    upgrade_to_head(migration_sync_url)
    engine = sqlalchemy.create_engine(migration_sync_url)  # síncrono: o conftest exporta outro
    try:
        columns = {c["name"]: c for c in inspect(engine).get_columns("outbox")}
    finally:
        engine.dispose()

    assert "traceparent" in columns
    assert columns["traceparent"]["nullable"] is True


async def test_complete_grava_o_traceparent_do_contexto_corrente(channels_db, spans: Any):
    from commerce_agents.infrastructure.persistence.inbound_ledger import SqlInboundLedger

    engine, factory = channels_db
    ledger = SqlInboundLedger(factory)
    await ledger.claim(_inbound(1))

    with _tracer().start_as_current_span("conversation.turn") as turn:
        await ledger.complete("wamid.T1", _reply(1), at=AT)

    assert await _stored_traceparents(engine) == [_traceparent(turn)]


async def test_repositorio_grava_o_traceparent_e_null_sem_contexto(channels_db, spans: Any):
    from commerce_agents.infrastructure.persistence.outbox import SqlOutboxRepository

    engine, factory = channels_db
    repository = SqlOutboxRepository(factory)

    with _tracer().start_as_current_span("handoff") as current:
        await repository.add(TOPIC_OUTBOUND, "k", _reply(2))
    await repository.add(TOPIC_OUTBOUND, "k", _reply(3))

    assert await _stored_traceparents(engine) == [_traceparent(current), None]


# ------------------------------------------------------------------ 6. relay


async def test_relay_publica_cada_linha_com_o_contexto_dela(channels_db, spans: Any):
    from commerce_agents.infrastructure.persistence.outbox import SqlOutboxRepository

    _, factory = channels_db
    repository = SqlOutboxRepository(factory)
    origins = []
    for n in (4, 5):
        with _tracer().start_as_current_span(f"turno-{n}") as origin:
            await repository.add(TOPIC_OUTBOUND, "k", _reply(n))
        origins.append(origin.get_span_context())
    bus = HeaderBus()

    with _tracer().start_as_current_span("laco-do-relay") as loop:
        assert await _relay(factory, bus).publish_pending() == 2

    publishes = [s for s in spans.get_finished_spans() if s.name == "outbox.publish"]
    assert len(publishes) == 2
    for origin, publish, (_, _, headers) in zip(origins, publishes, bus.published, strict=True):
        assert publish.context.trace_id == origin.trace_id
        assert publish.parent is not None and publish.parent.span_id == origin.span_id
        assert headers["traceparent"] == (
            f"00-{origin.trace_id:032x}-{publish.context.span_id:016x}-01"
        )
        assert publish.context.trace_id != loop.get_span_context().trace_id


async def test_linha_sem_traceparent_publica_sem_header_e_sem_erro(channels_db, spans: Any):
    from commerce_agents.infrastructure.persistence.outbox import SqlOutboxRepository

    _, factory = channels_db
    await SqlOutboxRepository(factory).add(TOPIC_OUTBOUND, "k", _reply(6))
    bus = HeaderBus()

    assert await _relay(factory, bus).publish_pending() == 1

    (_, _, headers) = bus.published[0]
    assert "traceparent" not in headers
    assert [s for s in spans.get_finished_spans() if s.name == "outbox.publish"] == []


# ------------------------------------------------------------------ 7. ponta a ponta


async def test_turno_outbox_relay_consumidor_e_envio_num_unico_trace(channels_db, spans: Any):
    from commerce_agents.infrastructure.messaging.senders import ChannelRouter
    from commerce_agents.infrastructure.persistence.inbound_ledger import SqlInboundLedger
    from commerce_agents.infrastructure.telemetry import consumer_span

    _, factory = channels_db
    ledger = SqlInboundLedger(factory)
    await ledger.claim(_inbound(7))
    reply = _reply(7)
    with _tracer().start_as_current_span("conversation.turn") as turn:
        await ledger.complete("wamid.T7", reply, at=AT)
    bus = HeaderBus()
    await _relay(factory, bus).publish_pending()
    sender = SpySender()

    (topic, event, headers) = bus.published[0]
    with consumer_span(topic, [(k, v.encode()) for k, v in headers.items()]):
        await ChannelRouter({Channel.WHATSAPP: sender}).send(event)

    finished = spans.get_finished_spans()
    by_name = {s.name: s for s in finished}
    assert {"outbox.publish", f"{TOPIC_OUTBOUND} process", "channel.send"} <= set(by_name)
    trace_id = turn.get_span_context().trace_id
    for name in ("outbox.publish", f"{TOPIC_OUTBOUND} process", "channel.send"):
        assert by_name[name].context.trace_id == trace_id, name
    assert by_name["channel.send"].attributes["conversation_id"] == reply.conversation_id
    assert sender.sent == [event]
