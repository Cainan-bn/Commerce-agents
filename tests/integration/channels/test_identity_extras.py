"""SqlIdentityResolver: canal web (customer_id da sessão), telefone vazio e Instagram anônimo."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.persistence.identity import SqlIdentityResolver
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration


async def test_web_resolve_pelo_customer_id_e_instagram_e_telefone_vazio_sao_anonimos(channels_db):
    engine, factory = channels_db
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO customers (customer_id, name, email, phone, created_at) "
                "VALUES ('C0001', 'Maria', 'm@example.com', '+5511 90000-0001', :at)"
            ),
            {"at": datetime(2025, 5, 28, tzinfo=UTC)},
        )
    resolver = SqlIdentityResolver(factory)

    assert await resolver.resolve(Channel.WEB, "C0001") == "C0001"
    assert await resolver.resolve(Channel.WEB, "sess-anonima") is None
    assert await resolver.resolve(Channel.INSTAGRAM, "IGSID-1") is None
    assert await resolver.resolve(Channel.WHATSAPP, "---") is None
