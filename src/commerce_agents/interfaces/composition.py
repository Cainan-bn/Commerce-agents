"""Composição das dependências por processo (api e worker). Único lugar que conhece tudo."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.channels import TOPIC_HANDOFF, TOPIC_OUTBOUND
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.use_cases.handle_inbound import HandleInboundMessage
from commerce_agents.application.use_cases.request_handoff import (
    ClaimHandoff,
    CloseHandoff,
    HumanReply,
    RequestHandoff,
)
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.agents.checkpointer import (
    LazyPostgresSaver,
    create_postgres_checkpointer,
)
from commerce_agents.infrastructure.agents.graph import GraphDeps, build_graph
from commerce_agents.infrastructure.agents.handlers import make_search_policies_handler
from commerce_agents.infrastructure.agents.memory import SqlCustomerMemory
from commerce_agents.infrastructure.agents.router import LLMIntentRouter
from commerce_agents.infrastructure.agents.service import ConversationService
from commerce_agents.infrastructure.mcp.executor import ToolExecutor
from commerce_agents.infrastructure.messaging.bus import KafkaEventBus, consume
from commerce_agents.infrastructure.messaging.hub import PanelHub
from commerce_agents.infrastructure.messaging.senders import (
    ChannelRouter,
    InstagramSender,
    WhatsAppSender,
)
from commerce_agents.infrastructure.messaging.topics import PanelCustomerMessage
from commerce_agents.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
)
from commerce_agents.infrastructure.persistence.handoffs import SqlHandoffRepository
from commerce_agents.infrastructure.persistence.idempotency import SqlIdempotencyRegistry
from commerce_agents.infrastructure.persistence.identity import SqlIdentityResolver
from commerce_agents.infrastructure.persistence.inbound_ledger import SqlInboundLedger
from commerce_agents.infrastructure.persistence.migrate import sync_url_from_env
from commerce_agents.infrastructure.persistence.outbox import SqlOutboxRelay
from commerce_agents.infrastructure.persistence.repositories import SqlConversationRepository
from commerce_agents.infrastructure.persistence.token_store import SqlConfirmationTokenStore
from commerce_agents.infrastructure.rag.embedder import FastEmbedEmbedder
from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever
from commerce_agents.interfaces.api import ApiDeps

logger = logging.getLogger(__name__)

DEFAULT_KAFKA_BOOTSTRAP = "localhost:9092"
DEFAULT_STORE_BASE_URL = "http://localhost:8001"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Settings:
    """Configuração por ambiente. Segredos só vêm de variáveis de ambiente."""

    kafka_bootstrap: str
    store_base_url: str
    whatsapp_app_secret: str
    whatsapp_verify_token: str
    whatsapp_access_token: str
    whatsapp_phone_number_id: str
    instagram_app_secret: str
    instagram_verify_token: str
    instagram_access_token: str
    web_session_secret: str
    panel_token: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        return cls(
            kafka_bootstrap=env.get("KAFKA_BOOTSTRAP", DEFAULT_KAFKA_BOOTSTRAP),
            store_base_url=env.get("STORE_BASE_URL", DEFAULT_STORE_BASE_URL),
            whatsapp_app_secret=env.get("WHATSAPP_APP_SECRET", ""),
            whatsapp_verify_token=env.get("WHATSAPP_VERIFY_TOKEN", ""),
            whatsapp_access_token=env.get("WHATSAPP_ACCESS_TOKEN", ""),
            whatsapp_phone_number_id=env.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            instagram_app_secret=env.get("INSTAGRAM_APP_SECRET", ""),
            instagram_verify_token=env.get("INSTAGRAM_VERIFY_TOKEN", ""),
            instagram_access_token=env.get("INSTAGRAM_ACCESS_TOKEN", ""),
            web_session_secret=env.get("WEB_SESSION_SECRET", ""),
            panel_token=env.get("PANEL_TOKEN", ""),
        )


class UnconfiguredLLM:
    """Placeholder até existir um provider real: o grafo trata a falha com resposta fixa."""

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        raise RuntimeError("LLM não configurado")


class BusHandoffNotifier:
    """Publica o handoff no broker; o processo da API o entrega ao painel por WebSocket."""

    def __init__(self, bus: KafkaEventBus) -> None:
        self._bus = bus

    async def notify(self, request: HandoffRequested) -> None:
        await self._bus.publish(TOPIC_HANDOFF, request.conversation_id, request)


@dataclass
class WorkerRuntime:
    engine: AsyncEngine
    bus: KafkaEventBus
    http: httpx.AsyncClient
    checkpointer: LazyPostgresSaver
    handle_inbound: HandleInboundMessage
    relay: SqlOutboxRelay
    sender: ChannelRouter

    async def close(self) -> None:
        await self.bus.close()
        await self.http.aclose()
        await self.checkpointer.aclose()
        await self.engine.dispose()


def _session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_engine(sync_url_from_env().replace("+psycopg", "+asyncpg"))
    return engine, create_session_factory(engine)


async def build_worker(settings: Settings) -> WorkerRuntime:
    engine, factory = _session_factory()
    bus = KafkaEventBus(settings.kafka_bootstrap)
    handoffs = SqlHandoffRepository(factory)
    request_handoff = RequestHandoff(
        handoffs,
        SqlConversationRepository(factory),
        BusHandoffNotifier(bus),
        utcnow,
        lambda: uuid.uuid4().hex,
    )

    async def publish_event(event: StrictModel) -> None:
        if isinstance(event, HandoffRequested):
            await request_handoff.execute(event)
        else:
            logger.debug("evento %s sem consumidor nesta fase", type(event).__name__)

    async def forward_to_panel(handoff_id: str, text: str) -> None:
        await bus.publish(
            TOPIC_HANDOFF, handoff_id, PanelCustomerMessage(handoff_id=handoff_id, text=text)
        )

    http = httpx.AsyncClient(base_url=settings.store_base_url)
    retriever = HybridPolicyRetriever(factory, FastEmbedEmbedder())
    executor = ToolExecutor(
        client=http,
        tokens=SqlConfirmationTokenStore(factory, clock=utcnow),
        idempotency=SqlIdempotencyRegistry(factory),
        internal_handlers={"search_policies": make_search_policies_handler(retriever)},
    )
    llm = UnconfiguredLLM()
    checkpointer = create_postgres_checkpointer(sync_url_from_env().replace("+psycopg", ""))
    graph = build_graph(
        GraphDeps(
            llm=llm,
            router=LLMIntentRouter(llm),
            tools=executor,
            tokens=SqlConfirmationTokenStore(factory, clock=utcnow),
            publish_event=publish_event,
            clock=utcnow,
            memory=SqlCustomerMemory(factory),
            new_key=lambda: uuid.uuid4().hex,
        ),
        checkpointer=checkpointer,
    )
    channel_http = httpx.AsyncClient(timeout=10.0)
    return WorkerRuntime(
        engine=engine,
        bus=bus,
        http=http,
        checkpointer=checkpointer,
        handle_inbound=HandleInboundMessage(
            SqlInboundLedger(factory),
            SqlIdentityResolver(factory),
            ConversationService(lambda: graph),
            handoffs,
            forward_to_panel,
            utcnow,
        ),
        relay=SqlOutboxRelay(factory, bus),
        sender=ChannelRouter(
            {
                Channel.WHATSAPP: WhatsAppSender(
                    channel_http,
                    settings.whatsapp_access_token,
                    settings.whatsapp_phone_number_id,
                ),
                Channel.INSTAGRAM: InstagramSender(channel_http, settings.instagram_access_token),
            }
        ),
    )


def build_api(settings: Settings) -> ApiDeps:
    _, factory = _session_factory()
    bus = KafkaEventBus(settings.kafka_bootstrap)
    hub = PanelHub()
    handoffs = SqlHandoffRepository(factory)
    conversations = SqlConversationRepository(factory)

    async def handoff_events(event: StrictModel) -> None:
        if isinstance(event, HandoffRequested):
            await hub.notify(event)
        elif isinstance(event, PanelCustomerMessage):
            await hub.forward_customer_message(event.handoff_id, event.text)

    async def outbound_for_web(event: StrictModel) -> None:
        from commerce_agents.application.dto.channels import OutboundMessageReady

        if isinstance(event, OutboundMessageReady) and event.channel is Channel.WEB:
            await hub.send_to_conversation(event)

    async def background() -> None:
        instance = uuid.uuid4().hex[:8]
        import asyncio

        await asyncio.gather(
            consume(
                settings.kafka_bootstrap,
                TOPIC_HANDOFF,
                f"panel-{instance}",
                handoff_events,
                from_latest=True,
            ),
            consume(
                settings.kafka_bootstrap,
                TOPIC_OUTBOUND,
                f"web-{instance}",
                outbound_for_web,
                from_latest=True,
            ),
        )

    return ApiDeps(
        bus=bus,
        handoffs=handoffs,
        claim=ClaimHandoff(handoffs, clock=utcnow),
        reply=HumanReply(handoffs, clock=utcnow),
        close=CloseHandoff(handoffs, conversations, clock=utcnow),
        hub=hub,
        whatsapp_app_secret=settings.whatsapp_app_secret,
        whatsapp_verify_token=settings.whatsapp_verify_token,
        instagram_app_secret=settings.instagram_app_secret,
        instagram_verify_token=settings.instagram_verify_token,
        web_session_secret=settings.web_session_secret,
        panel_token=settings.panel_token,
        clock=utcnow,
        background=background,
    )
