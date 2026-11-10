"""API HTTP/WebSocket dos canais (ADR 0006/0014). Só adapta: regras vivem em application/."""

import asyncio
import hmac
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from commerce_agents.application.dto.channels import (
    TOPIC_INBOUND,
    TOPIC_OUTBOUND,
    conversation_id_for,
)
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.application.ports.channels import HandoffRepository
from commerce_agents.application.ports.messaging import EventBus
from commerce_agents.application.ports.repositories import CustomerRepository
from commerce_agents.application.use_cases.request_handoff import (
    ClaimHandoff,
    CloseHandoff,
    HumanReply,
)
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.domain.shared.errors import InvalidStateTransition
from commerce_agents.infrastructure.messaging.hub import PanelHub
from commerce_agents.interfaces.webhooks.instagram import normalize_instagram
from commerce_agents.interfaces.webhooks.signature import verify_signature
from commerce_agents.interfaces.webhooks.web import sign_web_session, verify_web_session
from commerce_agents.interfaces.webhooks.whatsapp import normalize_whatsapp

logger = logging.getLogger(__name__)

PANEL_DIR = Path(__file__).resolve().parents[3] / "panel"
DEMO_PAGE = Path(__file__).resolve().parent / "demo" / "index.html"
DEMO_CONVERSATIONS = Path(__file__).resolve().parents[3] / "data" / "demo" / "conversations.yaml"
DEMO_SESSION_TTL = timedelta(hours=1)
_WS_POLICY_VIOLATION = 1008
_MAX_TEXT = 4000


@dataclass
class ApiDeps:
    bus: EventBus
    handoffs: HandoffRepository
    claim: ClaimHandoff | None
    reply: HumanReply | None
    close: CloseHandoff | None
    hub: PanelHub | None
    whatsapp_app_secret: str
    whatsapp_verify_token: str
    instagram_app_secret: str
    instagram_verify_token: str
    web_session_secret: str
    panel_token: str
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    background: Callable[[], Awaitable[None]] | None = None  # consumidores ligados ao hub
    panel_dir: Path = PANEL_DIR
    # Modo demonstração (ADR 0020): sem ele as rotas /demo* nem são registradas.
    demo_mode: bool = False
    customers: CustomerRepository | None = None
    demo_conversations: Path = DEMO_CONVERSATIONS


class _WebMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class _DemoSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    customer_id: str = Field(min_length=1, max_length=64)


class _ClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(min_length=1, max_length=100)


class _ReplyBody(_ClaimBody):
    text: str = Field(min_length=1, max_length=_MAX_TEXT)


def _same(secret: str, candidate: str | None) -> bool:
    return (
        bool(secret)
        and candidate is not None
        and hmac.compare_digest(secret.encode(), candidate.encode())
    )


async def _run_background(job: Callable[[], Awaitable[None]]) -> None:
    await job()


def create_app(deps: ApiDeps) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        if deps.background is not None:
            task = asyncio.create_task(_run_background(deps.background))
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="CommerceAgents canais", docs_url=None, redoc_url=None, lifespan=lifespan)

    def require_panel(authorization: Annotated[str | None, Header()] = None) -> None:
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not authorization or not _same(deps.panel_token, token):
            raise HTTPException(status_code=401, detail="não autorizado")

    panel_auth = [Depends(require_panel)]

    async def publish_inbound(events: list[InboundMessageReceived]) -> None:
        for event in events:
            await deps.bus.publish(TOPIC_INBOUND, event.conversation_id, event)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ------------------------------------------------------------------ webhooks Meta
    def meta_routes(
        name: str,
        secret: str,
        verify_token: str,
        normalize: Callable[[Any], list[InboundMessageReceived]],
    ) -> None:
        @app.get(f"/webhooks/{name}", name=f"verify_{name}")
        async def verify(
            mode: Annotated[str | None, Query(alias="hub.mode")] = None,
            token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
            challenge: Annotated[str, Query(alias="hub.challenge")] = "",
        ) -> PlainTextResponse:
            if mode != "subscribe" or not _same(verify_token, token):
                raise HTTPException(status_code=403, detail="verificação recusada")
            return PlainTextResponse(challenge)

        @app.post(f"/webhooks/{name}", name=f"receive_{name}")
        async def receive(
            request: Request,
            signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
        ) -> dict[str, int]:
            body = await request.body()  # corpo BRUTO: a assinatura é conferida antes do JSON
            if not secret or not verify_signature(secret, body, signature):
                raise HTTPException(status_code=401, detail="assinatura inválida")
            try:
                payload = json.loads(body)
            except ValueError as error:
                raise HTTPException(status_code=400, detail="JSON inválido") from error
            events = normalize(payload)
            await publish_inbound(events)
            return {"accepted": len(events)}

    meta_routes(
        "whatsapp", deps.whatsapp_app_secret, deps.whatsapp_verify_token, normalize_whatsapp
    )
    meta_routes(
        "instagram", deps.instagram_app_secret, deps.instagram_verify_token, normalize_instagram
    )

    # ------------------------------------------------------------------ web
    @app.post("/webhooks/web")
    async def receive_web(
        message: _WebMessage,
        session_header: Annotated[str | None, Header(alias="X-Web-Session")] = None,
    ) -> dict[str, int]:
        now = deps.clock()
        session = verify_web_session(deps.web_session_secret, session_header or "", now)
        if session is None:
            raise HTTPException(status_code=401, detail="sessão inválida")
        if message.session_id != session.session_id:
            raise HTTPException(status_code=403, detail="sessão não corresponde")
        event = InboundMessageReceived(
            message_id=message.message_id,
            conversation_id=conversation_id_for(Channel.WEB, session.session_id),
            channel=Channel.WEB,
            customer_external_id=session.customer_id or session.session_id,
            text=message.text[:_MAX_TEXT],
            received_at=now,
        )
        await publish_inbound([event])
        return {"accepted": 1}

    if deps.demo_mode:
        _demo_routes(app, deps)

    # ------------------------------------------------------------------ painel
    @app.get("/panel")
    async def panel_page() -> FileResponse:
        return FileResponse(deps.panel_dir / "index.html")

    if (deps.panel_dir / "src").is_dir():
        app.mount("/panel/src", StaticFiles(directory=deps.panel_dir / "src"), name="panel-src")

    @app.get("/api/handoffs", dependencies=panel_auth)
    async def list_handoffs() -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in await deps.handoffs.list_active()]

    @app.get("/api/handoffs/{handoff_id}/messages", dependencies=panel_auth)
    async def handoff_messages(handoff_id: str) -> list[dict[str, Any]]:
        return [m.model_dump(mode="json") for m in await deps.handoffs.messages(handoff_id)]

    @app.post("/api/handoffs/{handoff_id}/claim", dependencies=panel_auth)
    async def claim_handoff(handoff_id: str, body: _ClaimBody) -> dict[str, Any]:
        assert deps.claim is not None
        record = await deps.claim.execute(handoff_id, body.agent)
        if record is None:
            raise HTTPException(status_code=409, detail="handoff já assumido ou encerrado")
        await _broadcast(
            {"type": "handoff_claimed", "handoff_id": handoff_id, "claimed_by": body.agent}
        )
        return record.model_dump(mode="json")

    @app.post("/api/handoffs/{handoff_id}/reply", dependencies=panel_auth)
    async def reply_handoff(handoff_id: str, body: _ReplyBody) -> dict[str, str]:
        assert deps.reply is not None
        try:
            out = await deps.reply.execute(handoff_id, body.agent, body.text)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="handoff não encontrado") from error
        except InvalidStateTransition as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await deps.bus.publish(TOPIC_OUTBOUND, out.conversation_id, out)
        return {"message_id": out.message_id}

    @app.post("/api/handoffs/{handoff_id}/close", dependencies=panel_auth)
    async def close_handoff(handoff_id: str) -> dict[str, Any]:
        assert deps.close is not None
        record = await deps.close.execute(handoff_id)
        if record is None:
            raise HTTPException(status_code=409, detail="handoff já encerrado ou inexistente")
        await _broadcast({"type": "handoff_closed", "handoff_id": handoff_id})
        return record.model_dump(mode="json")

    async def _broadcast(event: dict[str, Any]) -> None:
        if deps.hub is not None:
            await deps.hub.broadcast(event)

    # ------------------------------------------------------------------ WebSockets
    @app.websocket("/ws/panel")
    async def ws_panel(websocket: WebSocket, token: str | None = None) -> None:
        if deps.hub is None or not _same(deps.panel_token, token):
            await websocket.close(code=_WS_POLICY_VIOLATION)
            return
        await websocket.accept()
        deps.hub.add_panel(websocket)
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            logger.debug("painel desconectado")
        finally:
            deps.hub.remove_panel(websocket)

    @app.websocket("/ws/web/{conversation_id}")
    async def ws_web(websocket: WebSocket, conversation_id: str, token: str | None = None) -> None:
        session = verify_web_session(deps.web_session_secret, token or "", deps.clock())
        if (
            deps.hub is None
            or session is None
            or conversation_id != conversation_id_for(Channel.WEB, session.session_id)
        ):
            await websocket.close(code=_WS_POLICY_VIOLATION)
            return
        await websocket.accept()
        deps.hub.add_conversation(conversation_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            logger.debug("cliente web desconectado")
        finally:
            deps.hub.remove_conversation(conversation_id, websocket)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    return app


def _demo_routes(app: FastAPI, deps: ApiDeps) -> None:
    """Página e sessão do modo demonstração (ADR 0020). Nunca registradas fora dele."""

    @app.get("/demo")
    async def demo_page() -> FileResponse:
        return FileResponse(DEMO_PAGE, media_type="text/html; charset=utf-8")

    @app.get("/demo/conversations")
    async def demo_conversations() -> dict[str, Any]:
        data = yaml.safe_load(deps.demo_conversations.read_text(encoding="utf-8"))
        return {"conversations": data["conversations"]}

    @app.post("/demo/session")
    async def demo_session(body: _DemoSessionBody) -> dict[str, str]:
        if deps.customers is None or await deps.customers.get(body.customer_id) is None:
            raise HTTPException(status_code=404, detail="cliente não encontrado")
        session_id = uuid.uuid4().hex
        expires_at = deps.clock() + DEMO_SESSION_TTL
        token = sign_web_session(deps.web_session_secret, session_id, body.customer_id, expires_at)
        conversation_id = conversation_id_for(Channel.WEB, session_id)
        return {
            "token": token,
            "conversation_id": conversation_id,
            "ws_path": f"/ws/web/{quote(conversation_id, safe='')}",
        }
