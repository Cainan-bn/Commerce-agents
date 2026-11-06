"""Rotas da API de canais além do contrato base: web, painel (claim/reply/close) e WebSockets."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from commerce_agents.application.dto.channels import HandoffRecord, HandoffStatus
from commerce_agents.application.use_cases.request_handoff import (
    ClaimHandoff,
    CloseHandoff,
    HumanReply,
)
from commerce_agents.domain.conversation.conversation import Conversation, ConversationStatus
from commerce_agents.infrastructure.messaging.hub import PanelHub
from commerce_agents.interfaces.api import ApiDeps, create_app
from commerce_agents.interfaces.webhooks.web import sign_web_session
from tests.fakes.channels import InMemoryConversationRepository, InMemoryHandoffRepository
from tests.fakes.clock import BASE_TIME, FakeClock

pytestmark = pytest.mark.unit

WEB_SECRET = "web-secret-teste"  # pragma: allowlist secret
PANEL = {"Authorization": "Bearer painel-teste"}


class Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Any]] = []

    async def publish(self, topic: str, key: str, event: Any) -> None:
        self.published.append((topic, key, event))


class Env:
    def __init__(self) -> None:
        self.bus = Bus()
        self.handoffs = InMemoryHandoffRepository()
        self.conversations = InMemoryConversationRepository()
        self.hub = PanelHub()
        self.clock = FakeClock()
        deps = ApiDeps(
            bus=self.bus,
            handoffs=self.handoffs,
            claim=ClaimHandoff(self.handoffs, clock=self.clock),
            reply=HumanReply(self.handoffs, clock=self.clock),
            close=CloseHandoff(self.handoffs, self.conversations, clock=self.clock),
            hub=self.hub,
            whatsapp_app_secret="x",  # pragma: allowlist secret
            whatsapp_verify_token="v",  # pragma: allowlist secret
            instagram_app_secret="y",  # pragma: allowlist secret
            instagram_verify_token="w",  # pragma: allowlist secret
            web_session_secret=WEB_SECRET,
            panel_token="painel-teste",  # pragma: allowlist secret
            clock=self.clock,
        )
        self.app = create_app(deps)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    def session(self, session_id: str = "s1", customer: str = "C0001") -> str:
        return sign_web_session(WEB_SECRET, session_id, customer, BASE_TIME + timedelta(hours=1))

    async def seed(self, status: HandoffStatus = HandoffStatus.OPEN) -> None:
        await self.handoffs.create(
            HandoffRecord(
                handoff_id="h1",
                conversation_id="web:s1",
                status=status,
                reason="r",
                priority="normal",
                summary="s",
                created_at=BASE_TIME,
            )
        )
        await self.conversations.save(
            Conversation("web:s1", ConversationStatus.handoff, (), BASE_TIME)
        )


async def test_web_com_sessao_valida_publica_evento_do_cliente():
    env = Env()
    async with env.client() as client:
        response = await client.post(
            "/webhooks/web",
            json={"session_id": "s1", "message_id": "m1", "text": "oi"},
            headers={"X-Web-Session": env.session()},
        )

    assert response.status_code == 200
    topic, key, event = env.bus.published[0]
    assert (topic, key) == ("inbound.messages", "web:s1")
    assert event.customer_external_id == "C0001"


async def test_web_com_session_id_diferente_da_assinada_devolve_403():
    env = Env()
    async with env.client() as client:
        response = await client.post(
            "/webhooks/web",
            json={"session_id": "outra", "message_id": "m1", "text": "oi"},
            headers={"X-Web-Session": env.session()},
        )

    assert response.status_code == 403
    assert env.bus.published == []


async def test_webhook_com_json_invalido_apos_assinatura_devolve_400():
    import hashlib
    import hmac

    env = Env()
    body = b"{nao e json"
    signature = "sha256=" + hmac.new(b"x", body, hashlib.sha256).hexdigest()
    async with env.client() as client:
        response = await client.post(
            "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": signature}
        )

    assert response.status_code == 400


async def test_painel_claim_reply_close_e_mensagens():
    env = Env()
    await env.seed()
    async with env.client() as client:
        claimed = await client.post("/api/handoffs/h1/claim", json={"agent": "ana"}, headers=PANEL)
        again = await client.post("/api/handoffs/h1/claim", json={"agent": "bia"}, headers=PANEL)
        replied = await client.post(
            "/api/handoffs/h1/reply", json={"agent": "ana", "text": "Olá"}, headers=PANEL
        )
        messages = await client.get("/api/handoffs/h1/messages", headers=PANEL)
        closed = await client.post("/api/handoffs/h1/close", headers=PANEL)
        closed_again = await client.post("/api/handoffs/h1/close", headers=PANEL)

    assert claimed.status_code == 200 and again.status_code == 409
    assert replied.status_code == 200
    assert env.bus.published[-1][0] == "outbound.messages"
    assert [m["author"] for m in messages.json()] == ["agent_human"]
    assert closed.status_code == 200 and closed_again.status_code == 409
    conversation = await env.conversations.get("web:s1")
    assert conversation is not None and conversation.status is ConversationStatus.open


async def test_reply_em_handoff_inexistente_ou_nao_assumido():
    env = Env()
    await env.seed()
    async with env.client() as client:
        missing = await client.post(
            "/api/handoffs/zzz/reply", json={"agent": "a", "text": "x"}, headers=PANEL
        )
        not_claimed = await client.post(
            "/api/handoffs/h1/reply", json={"agent": "a", "text": "x"}, headers=PANEL
        )

    assert missing.status_code == 404
    assert not_claimed.status_code == 409


async def test_painel_e_health_respondem():
    env = Env()
    async with env.client() as client:
        health = await client.get("/health")
        page = await client.get("/panel")
        asset = await client.get("/panel/src/store.js")

    assert health.json() == {"status": "ok"}
    assert page.status_code == 200 and "<title>" in page.text
    assert asset.status_code == 200


def test_ws_web_exige_token_da_propria_sessao():
    env = Env()
    with TestClient(env.app) as client:
        for url in (
            "/ws/web/web:s1",
            f"/ws/web/web:s1?token={env.session('outra')}",
            "/ws/web/web:s1?token=lixo",
        ):
            with pytest.raises(Exception):  # noqa: B017 - starlette fecha com 1008
                with client.websocket_connect(url):
                    pass
        with client.websocket_connect(f"/ws/web/web:s1?token={env.session()}"):
            pass
