"""Conversation.resume (ADR 0014): handoff volta a open; open é idempotente; closed é erro."""

import pytest

from commerce_agents.domain.conversation.conversation import Conversation, ConversationStatus
from commerce_agents.domain.shared.errors import InvalidStateTransition
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit


def _conversation(status: ConversationStatus) -> Conversation:
    return Conversation(conversation_id="web:s1", status=status, messages=(), created_at=BASE_TIME)


def test_resume_de_handoff_volta_para_open():
    resumed = _conversation(ConversationStatus.handoff).resume(BASE_TIME)

    assert resumed.status is ConversationStatus.open


def test_resume_de_open_e_idempotente():
    conversation = _conversation(ConversationStatus.open)

    assert conversation.resume(BASE_TIME).status is ConversationStatus.open
    assert conversation.resume(BASE_TIME) == conversation.resume(BASE_TIME)


def test_resume_de_closed_e_erro():
    with pytest.raises(InvalidStateTransition):
        _conversation(ConversationStatus.closed).resume(BASE_TIME)
