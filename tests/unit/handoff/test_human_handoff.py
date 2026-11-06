"""ClaimHandoff, HumanReply e CloseHandoff (ADR 0014): claim atômico, resposta humana e retorno."""

import pytest

from commerce_agents.application.dto.channels import HandoffRecord, HandoffStatus
from commerce_agents.domain.conversation.conversation import Conversation, ConversationStatus
from commerce_agents.domain.shared.errors import InvalidStateTransition
from tests.fakes.channels import InMemoryConversationRepository, InMemoryHandoffRepository
from tests.fakes.clock import BASE_TIME, FakeClock

pytestmark = pytest.mark.unit

CONV = "instagram:IGSID-12345"


async def _seed(
    status: HandoffStatus,
) -> tuple[InMemoryHandoffRepository, InMemoryConversationRepository]:
    handoffs = InMemoryHandoffRepository()
    conversations = InMemoryConversationRepository()
    await handoffs.create(
        HandoffRecord(
            handoff_id="h-1",
            conversation_id=CONV,
            status=status,
            reason="motivo",
            priority="normal",
            summary="resumo",
            created_at=BASE_TIME,
        )
    )
    await conversations.save(
        Conversation(
            conversation_id=CONV,
            status=ConversationStatus.handoff,
            messages=(),
            created_at=BASE_TIME,
        )
    )
    return handoffs, conversations


async def test_claim_atomico_segundo_claim_devolve_none():
    from commerce_agents.application.use_cases.request_handoff import ClaimHandoff

    handoffs, _ = await _seed(HandoffStatus.OPEN)
    claim = ClaimHandoff(handoffs, clock=FakeClock())

    first = await claim.execute("h-1", "agente-ana")
    second = await claim.execute("h-1", "agente-bruno")

    assert first is not None and first.status is HandoffStatus.CLAIMED
    assert first.claimed_by == "agente-ana"
    assert second is None


async def test_resposta_humana_so_em_claimed_e_gera_mensagem_source_human():
    from commerce_agents.application.use_cases.request_handoff import HumanReply

    handoffs, _ = await _seed(HandoffStatus.CLAIMED)

    out = await HumanReply(handoffs, clock=FakeClock()).execute(
        "h-1", "agente-ana", "Olá, sou a Ana."
    )

    assert out.source == "human"
    assert out.message_id.startswith("human:")
    assert out.channel.value == "instagram"
    assert out.recipient_external_id == "IGSID-12345"
    assert out.text == "Olá, sou a Ana."
    stored = await handoffs.messages("h-1")
    assert [m.author for m in stored] == ["agent_human"]


@pytest.mark.parametrize("status", [HandoffStatus.OPEN, HandoffStatus.CLOSED])
async def test_resposta_humana_fora_de_claimed_e_erro(status: HandoffStatus):
    from commerce_agents.application.use_cases.request_handoff import HumanReply

    handoffs, _ = await _seed(status)

    with pytest.raises((InvalidStateTransition, ValueError)):
        await HumanReply(handoffs, clock=FakeClock()).execute("h-1", "agente-ana", "oi")


async def test_close_devolve_conversa_a_open_e_agente_volta_a_responder():
    from commerce_agents.application.use_cases.request_handoff import CloseHandoff

    handoffs, conversations = await _seed(HandoffStatus.CLAIMED)

    closed = await CloseHandoff(handoffs, conversations, clock=FakeClock()).execute("h-1")

    assert closed is not None and closed.status is HandoffStatus.CLOSED
    conversation = await conversations.get(CONV)
    assert conversation is not None and conversation.status is ConversationStatus.open
    assert await handoffs.get_active(CONV) is None
