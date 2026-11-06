"""conversation_id_for (ADR 0006): uma conversa por usuário e canal."""

import pytest

from commerce_agents.application.dto.channels import conversation_id_for
from commerce_agents.domain.conversation.channel import Channel

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("channel", "external_id", "expected"),
    [
        (Channel.WHATSAPP, "5511900000001", "whatsapp:5511900000001"),
        (Channel.INSTAGRAM, "IGSID-12345", "instagram:IGSID-12345"),
        (Channel.WEB, "sess-1", "web:sess-1"),
    ],
)
def test_conversation_id_por_usuario_e_canal(channel: Channel, external_id: str, expected: str):
    assert conversation_id_for(channel, external_id) == expected
