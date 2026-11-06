"""API de canais (ADR 0006/0014): webhooks, painel com Bearer e WebSockets, com fakes nos ports.

Contrato assumido para `create_app(deps)`: `deps` é a dataclass `ApiDeps` (interfaces/api.py) com
os campos bus, handoffs, claim, reply, close, hub, whatsapp_app_secret, whatsapp_verify_token,
instagram_app_secret, instagram_verify_token, web_session_secret e panel_token.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from commerce_agents.application.dto.channels import HandoffRecord, HandoffStatus
from commerce_agents.application.dto.events import HandoffRequested
from tests.fakes.channels import InMemoryHandoffRepository
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.integration

APP_SECRET = "app-secret-teste"  # pragma: allowlist secret
VERIFY_TOKEN = "verify-teste"  # pragma: allowlist secret
PANEL_TOKEN = "painel-teste"  # pragma: allowlist secret
WEB_SECRET = "web-secret-teste"  # pragma: allowlist secret


class RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Any]] = []

    async def publish(self, topic: str, key: str, event: Any) -> None:
        self.published.append((topic, key, event))


def _load(name: str) -> dict[str, Any]:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "fixtures" / "channels" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _signed(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _deps(bus: RecordingBus, handoffs: InMemoryHandoffRepository, hub: Any = None) -> Any:
    from commerce_agents.interfaces.api import ApiDeps

    return ApiDeps(
        bus=bus,
        handoffs=handoffs,
        claim=None,
        reply=None,
        close=None,
        hub=hub,
        whatsapp_app_secret=APP_SECRET,
        whatsapp_verify_token=VERIFY_TOKEN,
        instagram_app_secret=APP_SECRET,
        instagram_verify_token=VERIFY_TOKEN,
        web_session_secret=WEB_SECRET,
        panel_token=PANEL_TOKEN,
    )


def _app(
    bus: RecordingBus | None = None,
    handoffs: InMemoryHandoffRepository | None = None,
    hub: Any = None,
) -> Any:
    from commerce_agents.interfaces.api import create_app

    return create_app(_deps(bus or RecordingBus(), handoffs or InMemoryHandoffRepository(), hub))


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_webhook_whatsapp_assinado_publica_um_evento_e_responde_200():
    bus = RecordingBus()
    body = json.dumps(_load("whatsapp_text.json")).encode()

    async with _client(_app(bus)) as client:
        response = await client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": _signed(body), "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert len(bus.published) == 1
    topic, key, event = bus.published[0]
    assert topic == "inbound.messages"
    assert key == "whatsapp:5511900000001"


async def test_webhook_whatsapp_assinatura_invalida_devolve_401_e_nada_publica():
    bus = RecordingBus()
    body = json.dumps(_load("whatsapp_text.json")).encode()

    async with _client(_app(bus)) as client:
        response = await client.post(
            "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=00"}
        )

    assert response.status_code == 401
    assert bus.published == []


async def test_verificacao_do_webhook_devolve_challenge_ou_403():
    async with _client(_app()) as client:
        ok = await client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "abc123",
            },
        )
        wrong = await client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "errado",
                "hub.challenge": "abc123",
            },
        )

    assert ok.status_code == 200
    assert ok.text == "abc123"
    assert wrong.status_code == 403


async def test_payload_de_status_responde_200_sem_publicar():
    bus = RecordingBus()
    body = json.dumps(_load("whatsapp_status.json")).encode()

    async with _client(_app(bus)) as client:
        response = await client.post(
            "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _signed(body)}
        )

    assert response.status_code == 200
    assert bus.published == []


async def test_webhook_web_sem_sessao_devolve_401():
    async with _client(_app()) as client:
        response = await client.post(
            "/webhooks/web", json={"session_id": "s1", "message_id": "m1", "text": "oi"}
        )

    assert response.status_code == 401


async def test_api_de_handoffs_sem_bearer_devolve_401():
    async with _client(_app()) as client:
        response = await client.get("/api/handoffs")

    assert response.status_code == 401


async def test_api_de_handoffs_com_bearer_lista_ativos():
    handoffs = InMemoryHandoffRepository()
    await handoffs.create(
        HandoffRecord(
            handoff_id="h-api",
            conversation_id="web:s1",
            status=HandoffStatus.OPEN,
            reason="motivo",
            priority="normal",
            summary="resumo",
            created_at=BASE_TIME,
        )
    )

    async with _client(_app(handoffs=handoffs)) as client:
        response = await client.get(
            "/api/handoffs", headers={"Authorization": f"Bearer {PANEL_TOKEN}"}
        )

    assert response.status_code == 200
    assert [item["handoff_id"] for item in response.json()] == ["h-api"]


def test_ws_painel_sem_token_fecha_1008():
    client = TestClient(_app())

    with pytest.raises(Exception):  # noqa: B017 - starlette levanta WebSocketDisconnect com code 1008
        with client.websocket_connect("/ws/panel"):
            pass


def test_ws_painel_com_token_recebe_novo_handoff():
    from commerce_agents.infrastructure.messaging.hub import PanelHub

    hub = PanelHub()
    app = _app(hub=hub)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/panel?token={PANEL_TOKEN}") as ws:
            client.portal.call(
                hub.notify,
                HandoffRequested(
                    conversation_id="web:s1",
                    reason="motivo",
                    priority="high",
                    summary="resumo",
                    requested_at=BASE_TIME,
                ),
            )
            message = ws.receive_json()

    assert "web:s1" in json.dumps(message)


WEB_SECRET_FOR_WS = WEB_SECRET


def _web_token(session_id: str, *, secret: str = WEB_SECRET_FOR_WS, expires_in: int = 3600) -> str:
    """Token de sessão web válido para `session_id` (expiração relativa ao relógio real)."""
    from commerce_agents.interfaces.webhooks.web import sign_web_session

    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return sign_web_session(secret, session_id, "C0001", expires_at)


def _ws_out(conversation_id: str, text: str) -> Any:
    from commerce_agents.application.dto.channels import OutboundMessageReady
    from commerce_agents.domain.conversation.channel import Channel

    return OutboundMessageReady(
        message_id=f"reply:{text}",
        conversation_id=conversation_id,
        channel=Channel.WEB,
        recipient_external_id=conversation_id.split(":", 1)[1],
        text=text,
        source="agent",
        created_at=BASE_TIME,
    )


def test_ws_web_recebe_so_a_propria_conversa():
    from commerce_agents.infrastructure.messaging.hub import PanelHub

    hub = PanelHub()
    app = _app(hub=hub)

    with TestClient(app) as client:
        with (
            client.websocket_connect(f"/ws/web/web:A?token={_web_token('A')}") as ws_a,
            client.websocket_connect(f"/ws/web/web:B?token={_web_token('B')}") as ws_b,
        ):
            client.portal.call(hub.send_to_conversation, _ws_out("web:A", "so para A"))
            client.portal.call(hub.send_to_conversation, _ws_out("web:B", "so para B"))
            first_for_b = ws_b.receive_json()
            first_for_a = ws_a.receive_json()

    assert "so para B" in json.dumps(first_for_b)
    assert "so para A" in json.dumps(first_for_a)
    assert "so para A" not in json.dumps(first_for_b)


def test_ws_web_sem_token_fecha_1008():
    from starlette.websockets import WebSocketDisconnect

    with TestClient(_app()) as client:
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect("/ws/web/web:A"):
                pass

    assert refused.value.code == 1008


def test_ws_web_token_adulterado_fecha_1008():
    from starlette.websockets import WebSocketDisconnect

    token = _web_token("A")
    payload, _, digest = token.partition(".")
    tampered = f"{payload}.{'0' if digest[0] != '0' else '1'}{digest[1:]}"

    with TestClient(_app()) as client:
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(f"/ws/web/web:A?token={tampered}"):
                pass

    assert refused.value.code == 1008


def test_ws_web_token_expirado_fecha_1008():
    from starlette.websockets import WebSocketDisconnect

    with TestClient(_app()) as client:
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(f"/ws/web/web:A?token={_web_token('A', expires_in=-60)}"):
                pass

    assert refused.value.code == 1008


def test_token_de_a_nao_ouve_a_conversa_de_b_e_nada_chega():
    from starlette.websockets import WebSocketDisconnect

    from commerce_agents.infrastructure.messaging.hub import PanelHub

    hub = PanelHub()
    with TestClient(_app(hub=hub)) as client:
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(f"/ws/web/web:B?token={_web_token('A')}"):
                pass
        assert refused.value.code == 1008
