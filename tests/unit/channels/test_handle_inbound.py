"""HandleInboundMessage (ADR 0014): ledger exatamente-uma-vez, identidade, handoff ativo."""

from typing import Any

import pytest

from commerce_agents.application.dto.agents import OutboundReply
from commerce_agents.application.dto.channels import (
    HandoffRecord,
    HandoffStatus,
    OutboundMessageReady,
)
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel
from tests.fakes.channels import (
    CollectingPanelForwarder,
    FakeConversationService,
    FakeIdentityResolver,
    InMemoryHandoffRepository,
    InMemoryInboundLedger,
)
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit

CONV = "whatsapp:5511900000001"


def _event(message_id: str = "wamid.1", text: str = "Oi") -> InboundMessageReceived:
    return InboundMessageReceived(
        message_id=message_id,
        conversation_id=CONV,
        channel=Channel.WHATSAPP,
        customer_external_id="5511900000001",
        text=text,
        received_at=BASE_TIME,
    )


def _reply(text: str = "Olá, em que posso ajudar?") -> OutboundReply:
    return OutboundReply(conversation_id=CONV, text=text, agent="pedidos")


def _use_case(
    *,
    ledger: InMemoryInboundLedger | None = None,
    identity: FakeIdentityResolver | None = None,
    service: FakeConversationService | None = None,
    handoffs: InMemoryHandoffRepository | None = None,
    forward: CollectingPanelForwarder | None = None,
) -> dict[str, Any]:
    from commerce_agents.application.use_cases.handle_inbound import HandleInboundMessage

    parts = {
        "ledger": ledger or InMemoryInboundLedger(),
        "identity": identity
        or FakeIdentityResolver({(Channel.WHATSAPP, "5511900000001"): "C0001"}),
        "service": service or FakeConversationService(reply=_reply()),
        "handoffs": handoffs or InMemoryHandoffRepository(),
        "forward": forward or CollectingPanelForwarder(),
    }
    from tests.fakes.clock import FakeClock

    parts["use_case"] = HandleInboundMessage(
        parts["ledger"],
        parts["identity"],
        parts["service"],
        parts["handoffs"],
        parts["forward"],
        FakeClock(),
    )
    return parts


async def test_mensagem_nova_chama_servico_e_converte_resposta():
    parts = _use_case()

    out = await parts["use_case"].execute(_event("wamid.1"))

    assert isinstance(out, OutboundMessageReady)
    assert out.message_id == "reply:wamid.1"
    assert out.conversation_id == CONV
    assert out.channel is Channel.WHATSAPP
    assert out.recipient_external_id == "5511900000001"
    assert out.source == "agent"
    assert out.text == "Olá, em que posso ajudar?"
    assert parts["service"].calls[0][1] == "C0001"
    assert parts["ledger"].status("wamid.1") == "done"


async def test_mensagem_ja_concluida_devolve_none_sem_chamar_servico():
    ledger = InMemoryInboundLedger()
    parts = _use_case(ledger=ledger)
    await parts["use_case"].execute(_event("wamid.2"))
    calls_before = len(parts["service"].calls)

    out = await parts["use_case"].execute(_event("wamid.2"))

    assert out is None
    assert len(parts["service"].calls) == calls_before


async def test_retry_de_mensagem_nao_concluida_reprocessa():
    ledger = InMemoryInboundLedger()
    failing = FakeConversationService(error=RuntimeError("falha transitória"))
    parts = _use_case(ledger=ledger, service=failing)
    with pytest.raises(RuntimeError):
        await parts["use_case"].execute(_event("wamid.3"))

    parts["service"].error = None
    parts["service"].reply = _reply("segunda tentativa")
    out = await parts["use_case"].execute(_event("wamid.3"))

    assert out is not None
    assert out.text == "segunda tentativa"


async def test_cliente_anonimo_recebe_customer_id_vazio():
    parts = _use_case(identity=FakeIdentityResolver({}))

    await parts["use_case"].execute(_event("wamid.4"))

    assert parts["service"].calls[0][1] == ""


async def test_excecao_do_servico_nao_completa_o_ledger():
    ledger = InMemoryInboundLedger()
    parts = _use_case(ledger=ledger, service=FakeConversationService(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        await parts["use_case"].execute(_event("wamid.5"))

    assert ledger.status("wamid.5") != "done"
    assert await ledger.claim(_event("wamid.5")) == "retry"


async def test_handoff_ativo_grava_mensagem_notifica_e_nao_chama_agente():
    handoffs = InMemoryHandoffRepository()
    await handoffs.create(
        HandoffRecord(
            handoff_id="h-1",
            conversation_id=CONV,
            status=HandoffStatus.OPEN,
            reason="cliente pediu humano",
            priority="normal",
            summary="resumo",
            created_at=BASE_TIME,
        )
    )
    forward = CollectingPanelForwarder()
    parts = _use_case(handoffs=handoffs, forward=forward)

    first = await parts["use_case"].execute(_event("wamid.6", "ainda aí?"))

    assert parts["service"].calls == []
    stored = handoffs.messages_by_handoff["h-1"]
    assert [m.author for m in stored] == ["customer"]
    assert stored[0].text == "ainda aí?"
    assert forward.forwarded == [("h-1", "ainda aí?")]
    assert first is not None
    assert first.source == "system"


async def test_handoff_ativo_so_confirma_a_primeira_mensagem():
    handoffs = InMemoryHandoffRepository()
    await handoffs.create(
        HandoffRecord(
            handoff_id="h-2",
            conversation_id=CONV,
            status=HandoffStatus.OPEN,
            reason="motivo",
            priority="normal",
            summary="resumo",
            created_at=BASE_TIME,
        )
    )
    parts = _use_case(handoffs=handoffs)

    first = await parts["use_case"].execute(_event("wamid.7", "um"))
    second = await parts["use_case"].execute(_event("wamid.8", "dois"))

    assert first is not None and first.source == "system"
    assert second is None
    assert parts["service"].calls == []
