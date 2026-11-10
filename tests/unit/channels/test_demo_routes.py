"""Rotas do modo demonstração (ADR 0020).

Contrato fixado:
- `ApiDeps.demo_mode: bool = False` e `ApiDeps.customers: CustomerRepository | None`;
  `Settings.demo_mode` vem de `DEMO_MODE` ("true"/"1" liga; ausente ou "false" desliga);
- sem o modo: nenhuma rota `/demo*` existe (404);
- com o modo: `GET /demo` (HTML), `GET /demo/conversations` (`{"conversations": [...]}`, o
  roteiro de data/demo/conversations.yaml) e `POST /demo/session` `{"customer_id"}` ->
  `{"token", "conversation_id", "ws_path"}`, com sessão nova a cada chamada, assinada com o
  `WEB_SESSION_SECRET` e válida por no máximo 1 h (`ws_path` = `/ws/web/<conversation_id>`,
  com ou sem `?token=`); cliente inexistente -> 404; corpo inválido -> 422;
- o token emitido serve no webhook web e no WebSocket da conversa (fluxo existente).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
import yaml
from starlette.testclient import TestClient

from commerce_agents.application.dto.channels import conversation_id_for
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.domain.customer.customer import Customer
from commerce_agents.infrastructure.messaging.hub import PanelHub
from commerce_agents.interfaces.webhooks.web import verify_web_session
from tests.fakes.channels import InMemoryCustomerRepository, InMemoryHandoffRepository
from tests.fakes.clock import BASE_TIME, FakeClock

pytestmark = pytest.mark.unit

WEB_SECRET = "web-secret-demo"  # pragma: allowlist secret
ROTEIRO = Path(__file__).resolve().parents[3] / "data" / "demo" / "conversations.yaml"
DEMO_ROUTES = [
    ("GET", "/demo"),
    ("GET", "/demo/"),
    ("GET", "/demo/conversations"),
    ("POST", "/demo/session"),
    ("GET", "/demo/index.html"),
]


class Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Any]] = []

    async def publish(self, topic: str, key: str, event: Any) -> None:
        self.published.append((topic, key, event))


def _customer(customer_id: str) -> Customer:
    return Customer(
        customer_id=customer_id,
        name="Cliente Demo",
        email=f"{customer_id.lower()}@example.com",
        phone="+5511 90000-0000",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _app(demo_mode: bool) -> tuple[Any, Bus, FakeClock]:
    from commerce_agents.interfaces.api import ApiDeps, create_app

    bus, clock = Bus(), FakeClock()
    deps = ApiDeps(
        bus=bus,
        handoffs=InMemoryHandoffRepository(),
        claim=None,
        reply=None,
        close=None,
        hub=PanelHub(),
        whatsapp_app_secret="x",  # pragma: allowlist secret
        whatsapp_verify_token="v",  # pragma: allowlist secret
        instagram_app_secret="y",  # pragma: allowlist secret
        instagram_verify_token="w",  # pragma: allowlist secret
        web_session_secret=WEB_SECRET,
        panel_token="painel-teste",  # pragma: allowlist secret
        clock=clock,
        demo_mode=demo_mode,
        customers=InMemoryCustomerRepository([_customer("C0167"), _customer("C0200")]),
    )
    return create_app(deps), bus, clock


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


# ------------------------------------------------------------------ configuração


@pytest.mark.parametrize(
    ("env", "esperado"),
    [({}, False), ({"DEMO_MODE": "false"}, False), ({"DEMO_MODE": "true"}, True)],
)
def test_settings_le_demo_mode(env: dict[str, str], esperado: bool):
    from commerce_agents.interfaces.composition import Settings

    assert Settings.from_env(env).demo_mode is esperado


# ------------------------------------------------------------------ desligado


@pytest.mark.parametrize(("method", "path"), DEMO_ROUTES)
async def test_sem_modo_demonstracao_nenhuma_rota_demo_existe(method: str, path: str):
    app, _, _ = _app(demo_mode=False)
    async with _client(app) as client:
        response = await client.request(method, path, json={"customer_id": "C0167"})

    assert response.status_code == 404


def test_sem_modo_demonstracao_o_app_nao_registra_rotas_demo():
    app, _, _ = _app(demo_mode=False)

    paths = [getattr(route, "path", "") for route in app.routes]
    assert not [p for p in paths if p.startswith("/demo")]


# ------------------------------------------------------------------ ligado


async def test_pagina_demo_e_html():
    app, _, _ = _app(demo_mode=True)
    async with _client(app) as client:
        response = await client.get("/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "modo demonstração" in response.text.lower()


async def test_conversations_devolve_o_roteiro():
    app, _, _ = _app(demo_mode=True)
    async with _client(app) as client:
        response = await client.get("/demo/conversations")

    assert response.status_code == 200
    roteiro = yaml.safe_load(ROTEIRO.read_text(encoding="utf-8"))["conversations"]
    conversas = response.json()["conversations"]
    assert [{k: c[k] for k in ("id", "title", "customer_id", "messages")} for c in conversas] == [
        {k: c[k] for k in ("id", "title", "customer_id", "messages")} for c in roteiro
    ]


async def test_session_emite_token_valido_por_ate_uma_hora():
    app, _, clock = _app(demo_mode=True)
    async with _client(app) as client:
        response = await client.post("/demo/session", json={"customer_id": "C0167"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"token", "conversation_id", "ws_path"}
    session = verify_web_session(WEB_SECRET, body["token"], clock())
    assert session is not None
    assert session.customer_id == "C0167"
    assert body["conversation_id"] == conversation_id_for(Channel.WEB, session.session_id)
    assert session.expires_at <= BASE_TIME + timedelta(hours=1)
    assert verify_web_session(WEB_SECRET, body["token"], BASE_TIME + timedelta(hours=1)) is None
    assert unquote(body["ws_path"].split("?")[0]) == f"/ws/web/{body['conversation_id']}"


async def test_cada_sessao_tem_session_id_novo():
    app, _, _ = _app(demo_mode=True)
    async with _client(app) as client:
        first = (await client.post("/demo/session", json={"customer_id": "C0167"})).json()
        second = (await client.post("/demo/session", json={"customer_id": "C0167"})).json()

    assert first["conversation_id"] != second["conversation_id"]
    assert first["token"] != second["token"]


async def test_cliente_inexistente_e_404():
    app, _, _ = _app(demo_mode=True)
    async with _client(app) as client:
        response = await client.post("/demo/session", json={"customer_id": "C9999"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body", [{}, {"customer_id": ""}, {"customer_id": 167}, {"customer_id": "C0167", "x": 1}]
)
async def test_corpo_invalido_e_422(body: dict[str, Any]):
    app, _, _ = _app(demo_mode=True)
    async with _client(app) as client:
        response = await client.post("/demo/session", json=body)

    assert response.status_code == 422


async def test_token_emitido_serve_no_webhook_web():
    app, bus, _ = _app(demo_mode=True)
    async with _client(app) as client:
        session = (await client.post("/demo/session", json={"customer_id": "C0200"})).json()
        session_id = session["conversation_id"].removeprefix("web:")
        response = await client.post(
            "/webhooks/web",
            json={"session_id": session_id, "message_id": "m-demo-1", "text": "oi"},
            headers={"X-Web-Session": session["token"]},
        )

    assert response.status_code == 200
    topic, key, event = bus.published[0]
    assert (topic, key) == ("inbound.messages", session["conversation_id"])
    assert event.customer_external_id == "C0200"


def test_token_emitido_abre_o_websocket_da_conversa():
    app, _, _ = _app(demo_mode=True)
    with TestClient(app) as client:
        session = client.post("/demo/session", json={"customer_id": "C0167"}).json()
        url = httpx.URL(session["ws_path"])
        ws_url = str(url) if url.params.get("token") else f"{url}?token={session['token']}"
        with client.websocket_connect(ws_url):
            pass
