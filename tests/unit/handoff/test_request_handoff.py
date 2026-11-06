"""RequestHandoff (ADR 0014): cria handoff open, muda a conversa, notifica e é idempotente."""

import pytest

from commerce_agents.application.dto.channels import HandoffStatus
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.domain.conversation.conversation import Conversation, ConversationStatus
from commerce_agents.domain.shared.errors import InvariantViolation
from tests.fakes.channels import (
    CollectingNotifier,
    InMemoryConversationRepository,
    InMemoryHandoffRepository,
)
from tests.fakes.clock import BASE_TIME, FakeClock

pytestmark = pytest.mark.unit

CONV = "whatsapp:5511900000001"


def _conversation(status: ConversationStatus = ConversationStatus.open) -> Conversation:
    return Conversation(conversation_id=CONV, status=status, messages=(), created_at=BASE_TIME)


def _request(reason: str = "cliente pediu humano") -> HandoffRequested:
    return HandoffRequested(
        conversation_id=CONV,
        reason=reason,
        priority="high",
        summary="Cliente quer trocar tamanho; sem resposta da política.",
        requested_at=BASE_TIME,
    )


def _use_case(handoffs, conversations, notifier):  # type: ignore[no-untyped-def]
    from commerce_agents.application.use_cases.request_handoff import RequestHandoff

    ids = iter(f"hand-{n}" for n in range(1, 100))
    return RequestHandoff(handoffs, conversations, notifier, FakeClock(), lambda: next(ids))


async def test_cria_handoff_open_com_prioridade_e_resumo():
    handoffs = InMemoryHandoffRepository()
    conversations = InMemoryConversationRepository()
    await conversations.save(_conversation())
    notifier = CollectingNotifier()

    record = await _use_case(handoffs, conversations, notifier).execute(_request())

    assert record.status is HandoffStatus.OPEN
    assert record.priority == "high"
    assert record.summary.startswith("Cliente quer trocar")
    assert record.conversation_id == CONV
    assert (await handoffs.get(record.handoff_id)) == record


async def test_muda_a_conversa_para_handoff_e_notifica_o_painel():
    handoffs = InMemoryHandoffRepository()
    conversations = InMemoryConversationRepository()
    await conversations.save(_conversation())
    notifier = CollectingNotifier()

    await _use_case(handoffs, conversations, notifier).execute(_request())

    saved = await conversations.get(CONV)
    assert saved is not None and saved.status is ConversationStatus.handoff
    assert len(notifier.notified) == 1


async def test_e_idempotente_quando_ja_ha_handoff_ativo():
    handoffs = InMemoryHandoffRepository()
    conversations = InMemoryConversationRepository()
    await conversations.save(_conversation())
    notifier = CollectingNotifier()
    use_case = _use_case(handoffs, conversations, notifier)

    first = await use_case.execute(_request())
    second = await use_case.execute(_request())

    assert second.handoff_id == first.handoff_id
    assert len(handoffs.records) == 1
    assert len(notifier.notified) == 1


async def test_motivo_vazio_e_erro():
    handoffs = InMemoryHandoffRepository()
    conversations = InMemoryConversationRepository()
    await conversations.save(_conversation())

    with pytest.raises((ValueError, InvariantViolation)):
        await _use_case(handoffs, conversations, CollectingNotifier()).execute(_request(reason=""))
