"""Span `channel.send` na entrega ao cliente (adendo do ADR 0017).

Nomes fixados: `ChannelRouter.send` (worker) e `PanelHub.send_to_conversation` (canal web, na
API) abrem `channel.send`, filho do contexto corrente (o consumidor de `outbound.messages`), com
`conversation_id`, `channel` e `message_id`. Nenhum texto do cliente vai para o span.
"""

from typing import Any

import pytest

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.domain.conversation.channel import Channel
from tests.fakes.clock import BASE_TIME
from tests.fakes.telemetry import span_text

pytestmark = pytest.mark.unit

SEGREDO = "texto-sentinela-do-cliente-0903f"


def _message(channel: Channel) -> OutboundMessageReady:
    return OutboundMessageReady(
        message_id="reply:m-envio-1",
        conversation_id=f"{channel.value}:u1",
        channel=channel,
        recipient_external_id="u1",
        text=SEGREDO,
        source="agent",
        created_at=BASE_TIME,
    )


class _Sender:
    async def send(self, message: Any) -> None:
        return None


class _Socket:
    async def send_json(self, data: Any) -> None:
        return None


def _parent() -> Any:
    from opentelemetry import trace

    return trace.get_tracer("teste-envio").start_as_current_span("outbound.messages process")


def _check(spans: Any, parent: Any, message: OutboundMessageReady) -> None:
    sends = [s for s in spans.get_finished_spans() if s.name == "channel.send"]
    assert len(sends) == 1
    (send,) = sends
    assert send.parent is not None
    assert send.parent.span_id == parent.get_span_context().span_id
    assert send.attributes["conversation_id"] == message.conversation_id
    assert send.attributes["channel"] == message.channel.value
    assert send.attributes["message_id"] == message.message_id
    assert SEGREDO not in span_text(send)


async def test_channel_router_abre_channel_send(spans: Any):
    from commerce_agents.infrastructure.messaging.senders import ChannelRouter

    message = _message(Channel.WHATSAPP)
    with _parent() as parent:
        await ChannelRouter({Channel.WHATSAPP: _Sender()}).send(message)

    _check(spans, parent, message)


async def test_hub_web_abre_channel_send(spans: Any):
    from commerce_agents.infrastructure.messaging.hub import PanelHub

    message = _message(Channel.WEB)
    hub = PanelHub()
    hub.add_conversation(message.conversation_id, _Socket())
    with _parent() as parent:
        await hub.send_to_conversation(message)

    _check(spans, parent, message)
