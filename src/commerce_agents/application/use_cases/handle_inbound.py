"""Processa uma mensagem recebida do canal: efeito exatamente-uma-vez e handoff ativo (ADR 0014)."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from commerce_agents.application.agents.replies import handoff_waiting
from commerce_agents.application.dto.agents import OutboundReply
from commerce_agents.application.dto.channels import (
    HandoffMessage,
    HandoffRecord,
    OutboundMessageReady,
)
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.application.ports.channels import (
    HandoffRepository,
    IdentityResolver,
    InboundLedger,
)

PanelForwarder = Callable[[str, str], Awaitable[None]]


class ConversationHandler(Protocol):
    """O orquestrador (`ConversationService`) visto pela camada de aplicação."""

    async def handle(self, event: InboundMessageReceived, customer_id: str) -> OutboundReply: ...


class HandleInboundMessage:
    def __init__(
        self,
        ledger: InboundLedger,
        identity: IdentityResolver,
        service: ConversationHandler,
        handoffs: HandoffRepository,
        forward_to_panel: PanelForwarder,
        clock: Callable[[], datetime],
    ) -> None:
        self._ledger = ledger
        self._identity = identity
        self._service = service
        self._handoffs = handoffs
        self._forward = forward_to_panel
        self._clock = clock

    async def execute(self, event: InboundMessageReceived) -> OutboundMessageReady | None:
        """Qualquer exceção deixa o ledger sem `done`, permitindo o retry do consumidor."""
        if await self._ledger.claim(event) == "done":
            return None
        active = await self._handoffs.get_active(event.conversation_id)
        if active is not None:
            out = await self._during_handoff(event, active)
        else:
            out = await self._by_agent(event)
        await self._ledger.complete(event.message_id, out, at=self._clock())
        return out

    async def _by_agent(self, event: InboundMessageReceived) -> OutboundMessageReady:
        customer_id = await self._identity.resolve(event.channel, event.customer_external_id)
        reply = await self._service.handle(event, customer_id or "")
        return self._outbound(event, reply.text, "agent", reply.citations)

    async def _during_handoff(
        self, event: InboundMessageReceived, record: HandoffRecord
    ) -> OutboundMessageReady | None:
        previous = await self._handoffs.messages(record.handoff_id)
        first = not any(message.author == "customer" for message in previous)
        await self._handoffs.add_message(
            HandoffMessage(
                handoff_id=record.handoff_id,
                author="customer",
                text=event.text,
                sent_at=event.received_at,
            )
        )
        await self._forward(record.handoff_id, event.text)
        return self._outbound(event, handoff_waiting(), "system") if first else None

    def _outbound(
        self,
        event: InboundMessageReceived,
        text: str,
        source: str,
        citations: tuple[str, ...] = (),
    ) -> OutboundMessageReady:
        return OutboundMessageReady.model_validate(
            {
                "message_id": f"reply:{event.message_id}",
                "conversation_id": event.conversation_id,
                "channel": event.channel,
                "recipient_external_id": event.customer_external_id,
                "text": text,
                "citations": citations,
                "source": source,
                "created_at": self._clock(),
            }
        )
