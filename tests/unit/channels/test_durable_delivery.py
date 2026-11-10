"""Idempotência durável dos senders: o `DeliveryLedger` sobrevive ao reinício do worker."""

from typing import Any

import httpx
import pytest

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.messaging.senders import (
    InstagramSender,
    SendRejectedError,
    WhatsAppSender,
)
from tests.fakes.clock import BASE_TIME
from tests.fakes.delivery import InMemoryDeliveryLedger

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
        return httpx.Response(queue.pop(0), json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _no_sleep(_: float) -> None:
    return None


def _whatsapp(client: httpx.AsyncClient, ledger: InMemoryDeliveryLedger) -> WhatsAppSender:
    return WhatsAppSender(client, "tok", "PNID", ledger=ledger, sleep=_no_sleep)


def test_port_delivery_ledger_existe_e_o_fake_o_satisfaz():
    from commerce_agents.application.ports.messaging import DeliveryLedger

    ledger: DeliveryLedger = InMemoryDeliveryLedger()

    assert hasattr(DeliveryLedger, "was_delivered")
    assert hasattr(DeliveryLedger, "mark_delivered")
    assert ledger is not None


def test_ledger_e_obrigatorio_na_construcao():
    seen: list[httpx.Request] = []

    with pytest.raises(TypeError):
        WhatsAppSender(_client([], seen), "tok", "PNID")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        InstagramSender(_client([], seen), "tok")  # type: ignore[call-arg]


async def test_mensagem_ja_entregue_nao_chama_o_canal():
    seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger({"reply:1": Channel.WHATSAPP})

    await _whatsapp(_client([200], seen), ledger).send(_message())

    assert len(seen) == 0
    assert ledger.marks == []


async def test_sucesso_marca_no_ledger_com_o_canal():
    seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger()

    await _whatsapp(_client([200], seen), ledger).send(_message())

    assert len(seen) == 1
    assert ledger.marks == [("reply:1", Channel.WHATSAPP)]
    assert await ledger.was_delivered("reply:1") is True


async def test_sucesso_apos_retry_marca_uma_vez_so():
    seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger()
    sender = InstagramSender(_client([503, 200], seen), "tok", ledger=ledger, sleep=_no_sleep)

    await sender.send(_message(Channel.INSTAGRAM))

    assert len(seen) == 2
    assert ledger.marks == [("reply:1", Channel.INSTAGRAM)]


async def test_4xx_nao_marca():
    seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger()

    with pytest.raises(SendRejectedError):
        await _whatsapp(_client([400], seen), ledger).send(_message())

    assert ledger.marks == []
    assert await ledger.was_delivered("reply:1") is False


async def test_falha_final_nao_marca():
    seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger()

    with pytest.raises(ConnectionError):
        await _whatsapp(_client([500, 500, 500], seen), ledger).send(_message())

    assert len(seen) == 3
    assert ledger.marks == []
    assert await ledger.was_delivered("reply:1") is False


async def test_falha_nao_impede_reenvio_posterior():
    seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger()
    sender = _whatsapp(_client([500, 500, 500, 200], seen), ledger)

    with pytest.raises(ConnectionError):
        await sender.send(_message())
    await sender.send(_message())

    assert len(seen) == 4
    assert ledger.marks == [("reply:1", Channel.WHATSAPP)]


async def test_dois_senders_com_o_mesmo_ledger_nao_enviam_duas_vezes():
    """Simula o reinício do worker: o segundo processo não tem memória, só o ledger."""
    first_seen: list[httpx.Request] = []
    second_seen: list[httpx.Request] = []
    ledger = InMemoryDeliveryLedger()
    first = _whatsapp(_client([200], first_seen), ledger)
    second = _whatsapp(_client([200, 200], second_seen), ledger)

    await first.send(_message())
    await second.send(_message())
    await second.send(_message(message_id="reply:2"))

    assert len(first_seen) == 1
    assert len(second_seen) == 1
    assert [mid for mid, _ in ledger.marks] == ["reply:1", "reply:2"]
