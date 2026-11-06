"""Contrato do SqlConversationRepository contra Postgres real."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.domain.conversation.conversation import ConversationStatus
from commerce_agents.infrastructure.persistence.repositories import SqlConversationRepository
from tests.unit.domain.builders import BASE_TIME, make_conversation, make_message

pytestmark = pytest.mark.integration


def _messages() -> tuple:
    return (
        make_message(message_id="MSG-1", text="oi", sent_at=BASE_TIME),
        make_message(
            message_id="MSG-2",
            text="quero ajuda",
            sent_at=BASE_TIME + timedelta(seconds=1),
        ),
        make_message(
            message_id="MSG-3",
            text="por favor",
            sent_at=BASE_TIME + timedelta(seconds=2),
        ),
    )


async def test_save_and_get_roundtrip_preserves_message_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlConversationRepository(session_factory)
    conversation = make_conversation(messages=_messages())

    await repository.save(conversation)

    assert await repository.get(conversation.conversation_id) == conversation


async def test_saving_same_conversation_twice_does_not_duplicate_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlConversationRepository(session_factory)
    conversation = make_conversation(messages=_messages())

    await repository.save(conversation)
    await repository.save(conversation)

    assert await repository.get(conversation.conversation_id) == conversation


async def test_duplicate_message_in_other_conversation_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlConversationRepository(session_factory)
    shared = make_message(message_id="MSG-1", text="oi", sent_at=BASE_TIME)
    original = make_conversation(conversation_id="CONV-A", messages=(shared,))
    conflicting = make_conversation(conversation_id="CONV-B", messages=(shared,))

    await repository.save(original)
    await repository.save(conflicting)

    assert await repository.get("CONV-A") == original
    assert await repository.get("CONV-B") == make_conversation(conversation_id="CONV-B")


async def test_handoff_status_survives_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlConversationRepository(session_factory)
    conversation = make_conversation(
        status=ConversationStatus.handoff,
        messages=_messages(),
    )

    await repository.save(conversation)

    loaded = await repository.get(conversation.conversation_id)
    assert loaded is not None
    assert loaded.status is ConversationStatus.handoff
    assert loaded == conversation


async def test_get_missing_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = SqlConversationRepository(session_factory)

    assert await repository.get("CONV-INEXISTENTE") is None
