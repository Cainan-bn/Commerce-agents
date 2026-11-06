"""Contrato de Conversation: idempotência, ordem e estados."""

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.domain.conversation.conversation import (
    Conversation,
    ConversationStatus,
    Message,
)
from commerce_agents.domain.shared.errors import InvalidStateTransition, InvariantViolation
from tests.unit.domain.builders import BASE_TIME, make_conversation, make_message


def test_status_values_match_contract() -> None:
    assert {status.value for status in ConversationStatus} == {
        "open",
        "handoff",
        "closed",
    }


def test_new_conversation_is_open() -> None:
    conversation = make_conversation()

    assert conversation.status is ConversationStatus.open
    assert conversation.messages == ()


def test_record_inbound_appends_message_and_returns_new_conversation() -> None:
    conversation = make_conversation()
    message = make_message(message_id="MSG-1")

    updated, is_new = conversation.record_inbound(message)

    assert is_new is True
    assert updated is not conversation
    assert updated.messages == (message,)
    assert conversation.messages == ()


def test_record_inbound_duplicate_is_idempotent() -> None:
    conversation = make_conversation()
    message = make_message(message_id="MSG-1")

    after_first, _ = conversation.record_inbound(message)
    after_duplicate, is_new = after_first.record_inbound(message)

    assert is_new is False
    assert after_duplicate.messages == after_first.messages
    assert after_duplicate == after_first


def test_record_inbound_preserves_arrival_order() -> None:
    conversation = make_conversation()
    messages = [
        make_message(message_id="MSG-1", sent_at=BASE_TIME),
        make_message(message_id="MSG-2", sent_at=BASE_TIME + timedelta(seconds=1)),
        make_message(message_id="MSG-3", sent_at=BASE_TIME + timedelta(seconds=2)),
    ]

    for message in messages:
        conversation, _ = conversation.record_inbound(message)

    assert [message.message_id for message in conversation.messages] == [
        "MSG-1",
        "MSG-2",
        "MSG-3",
    ]


@given(st.lists(st.integers(min_value=0, max_value=4), max_size=10))
def test_record_inbound_keeps_first_occurrence_in_order(message_indexes: list[int]) -> None:
    conversation = make_conversation()

    for position, index in enumerate(message_indexes):
        message = make_message(
            message_id=f"MSG-{index}",
            sent_at=BASE_TIME + timedelta(seconds=position),
        )
        conversation, _ = conversation.record_inbound(message)

    expected_ids = list(dict.fromkeys(f"MSG-{index}" for index in message_indexes))
    assert [message.message_id for message in conversation.messages] == expected_ids


def test_request_handoff_from_open() -> None:
    conversation = make_conversation()

    updated = conversation.request_handoff("cliente pediu humano", BASE_TIME)

    assert updated.status is ConversationStatus.handoff
    assert conversation.status is ConversationStatus.open


def test_request_handoff_is_idempotent() -> None:
    conversation = make_conversation().request_handoff("cliente pediu humano", BASE_TIME)

    repeated = conversation.request_handoff("outro motivo", BASE_TIME + timedelta(minutes=1))

    assert repeated.status is ConversationStatus.handoff
    assert repeated == conversation


def test_request_handoff_with_empty_reason_raises() -> None:
    conversation = make_conversation()

    with pytest.raises(InvariantViolation):
        conversation.request_handoff("", BASE_TIME)


def test_handoff_does_not_return_to_open() -> None:
    conversation = make_conversation().request_handoff("cliente pediu humano", BASE_TIME)

    repeated = conversation.request_handoff("cliente pediu humano", BASE_TIME)

    assert repeated.status is ConversationStatus.handoff


@pytest.mark.parametrize("status", [ConversationStatus.open, ConversationStatus.handoff])
def test_close_from_open_or_handoff(status: ConversationStatus) -> None:
    conversation = make_conversation(status=status)

    closed = conversation.close(BASE_TIME + timedelta(minutes=5))

    assert closed.status is ConversationStatus.closed
    assert conversation.status is status


def test_inbound_on_closed_conversation_raises() -> None:
    conversation = make_conversation(status=ConversationStatus.closed)

    with pytest.raises(InvalidStateTransition):
        conversation.record_inbound(make_message(message_id="MSG-1"))


def test_conversation_is_immutable() -> None:
    from dataclasses import FrozenInstanceError

    conversation = make_conversation()

    with pytest.raises(FrozenInstanceError):
        conversation.status = ConversationStatus.closed  # type: ignore[misc]


def test_message_exposes_contract_fields() -> None:
    message = make_message(message_id="MSG-9", text="oi", sent_at=BASE_TIME)

    assert message == Message(message_id="MSG-9", text="oi", sent_at=BASE_TIME)
    assert isinstance(conversation := make_conversation(), Conversation)
    assert conversation.conversation_id == "CONV-1"
