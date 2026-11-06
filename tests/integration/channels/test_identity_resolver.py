"""SqlIdentityResolver (ADR 0006): telefone normalizado por dígitos resolve o cliente do seed."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from commerce_agents.domain.conversation.channel import Channel
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration


async def _seed_customer(engine) -> None:  # type: ignore[no-untyped-def]
    """Cliente C0001 do seed, com o telefone exatamente como está em customers.jsonl."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO customers (customer_id, name, email, phone, created_at) "
                "VALUES ('C0001', 'Maria Araújo', 'maria.araujo@example.com', "
                "'+5511 90000-0001', :created)"
            ),
            {"created": datetime(2025, 5, 28, 14, 23, tzinfo=UTC)},
        )


def _resolver(factory):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.persistence.identity import SqlIdentityResolver

    return SqlIdentityResolver(factory)


@pytest.mark.parametrize(
    "external_id",
    ["+5511 90000-0001", "5511900000001", "+55 (11) 90000-0001", "11 90000-0001"],
)
async def test_telefone_em_formatos_diferentes_resolve_o_cliente(channels_db, external_id: str):
    engine, factory = channels_db
    await _seed_customer(engine)

    assert await _resolver(factory).resolve(Channel.WHATSAPP, external_id) == "C0001"


async def test_telefone_desconhecido_resolve_none(channels_db):
    engine, factory = channels_db
    await _seed_customer(engine)

    assert await _resolver(factory).resolve(Channel.WHATSAPP, "5511999999999") is None
