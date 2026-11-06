"""Senders da Meta, hub de WebSocket e decodificação de eventos (adaptadores sem rede real)."""

from typing import Any

import httpx
import pytest

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.messaging.hub import PanelHub
from commerce_agents.infrastructure.messaging.senders import (
    ChannelRouter,
    InstagramSender,
    SendRejectedError,
    WhatsAppSender,
)
from commerce_agents.infrastructure.messaging.topics import decode_event
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit


def _message(channel: Channel = Channel.WHATSAPP, message_id: str = "reply:1") -> Any:
    return OutboundMessageReady(
        message_id=message_id,
        conversation_id=f"{channel.value}:u1",
        channel=channel,
        recipient_external_id="u1",
        text="Olá",
        source="agent",
        created_at=BASE_TIME,
    )


def _client(statuses: list[int], seen: list[httpx.Request]) -> httpx.AsyncClient:
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = queue.pop(0)
        if status == 0:
            raise httpx.ConnectError("sem rede")
        return httpx.Response(status, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _no_sleep(_: float) -> None:
    return None


async def test_whatsapp_envia_texto_com_bearer_e_e_idempotente():
    seen: list[httpx.Request] = []
    sender = WhatsAppSender(_client([200, 200], seen), "tok", "PNID", sleep=_no_sleep)

    await sender.send(_message())
    await sender.send(_message())

    assert len(seen) == 1
    assert seen[0].url.path.endswith("/PNID/messages")
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert b'"body":"Ol' in seen[0].content.replace(b" ", b"")


async def test_5xx_e_timeout_repetem_ate_conseguir():
    seen: list[httpx.Request] = []
    sender = InstagramSender(_client([503, 0, 200], seen), "tok", sleep=_no_sleep)

    await sender.send(_message(Channel.INSTAGRAM))

    assert len(seen) == 3
    assert seen[0].url.path.endswith("/me/messages")


async def test_4xx_nao_repete():
    seen: list[httpx.Request] = []
    sender = WhatsAppSender(_client([400, 200], seen), "tok", "PNID", sleep=_no_sleep)

    with pytest.raises(SendRejectedError):
        await sender.send(_message())

    assert len(seen) == 1


async def test_falha_persistente_levanta_apos_tres_tentativas():
    seen: list[httpx.Request] = []
    sender = WhatsAppSender(_client([500, 500, 500], seen), "tok", "PNID", sleep=_no_sleep)

    with pytest.raises(ConnectionError):
        await sender.send(_message())

    assert len(seen) == 3


async def test_router_despacha_por_canal_e_ignora_canal_sem_sender():
    delivered: list[str] = []

    class Spy:
        async def send(self, message: OutboundMessageReady) -> None:
            delivered.append(message.channel.value)

    router = ChannelRouter({Channel.WEB: Spy()})

    await router.send(_message(Channel.WEB))
    await router.send(_message(Channel.WHATSAPP))

    assert delivered == ["web"]


class _Socket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[Any] = []

    async def send_json(self, data: Any) -> None:
        if self.fail:
            raise RuntimeError("fechado")
        self.sent.append(data)


async def test_hub_entrega_so_aos_sockets_da_conversa_e_remove_os_quebrados():
    hub = PanelHub()
    good, broken, other = _Socket(), _Socket(fail=True), _Socket()
    hub.add_conversation("web:a", good)
    hub.add_conversation("web:a", broken)
    hub.add_conversation("web:b", other)

    await hub.send(_message(Channel.WEB).model_copy(update={"conversation_id": "web:a"}))
    await hub.send(_message(Channel.WEB).model_copy(update={"conversation_id": "web:a"}))

    assert len(good.sent) == 2 and other.sent == []
    hub.remove_conversation("web:a", good)
    hub.remove_conversation("web:a", broken)
    hub.remove_conversation("web:zzz", good)


async def test_hub_notifica_o_painel_e_encaminha_mensagem_do_cliente():
    hub = PanelHub()
    panel = _Socket()
    hub.add_panel(panel)

    await hub.notify(
        HandoffRequested(
            conversation_id="web:a",
            reason="r",
            priority="high",
            summary="s",
            requested_at=BASE_TIME,
        )
    )
    await hub.forward_customer_message("h-1", "oi")
    hub.remove_panel(panel)
    await hub.broadcast({"type": "x"})

    assert [event["type"] for event in panel.sent] == ["handoff_new", "handoff_message"]


def test_decode_event_roundtrip_e_tipo_desconhecido():
    event = _message(Channel.WEB)

    assert decode_event(event.model_dump_json()) == event
    with pytest.raises(ValueError):
        decode_event('{"event_type": "nope"}')
    with pytest.raises(ValueError):
        decode_event("[]")
