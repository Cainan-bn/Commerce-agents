"""Hub de WebSocket em memória: painel de handoff e conversas web (ADR 0014)."""

import logging
from typing import Any, Protocol

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.infrastructure.telemetry import channel_send_span

logger = logging.getLogger(__name__)


class JsonSocket(Protocol):
    async def send_json(self, data: Any) -> None: ...


class PanelHub:
    """Conexões do painel e das conversas web. Implementa `HandoffNotifier` e `ChannelSender`."""

    def __init__(self) -> None:
        self._panel: set[JsonSocket] = set()
        self._conversations: dict[str, set[JsonSocket]] = {}

    def add_panel(self, socket: JsonSocket) -> None:
        self._panel.add(socket)

    def remove_panel(self, socket: JsonSocket) -> None:
        self._panel.discard(socket)

    def add_conversation(self, conversation_id: str, socket: JsonSocket) -> None:
        self._conversations.setdefault(conversation_id, set()).add(socket)

    def remove_conversation(self, conversation_id: str, socket: JsonSocket) -> None:
        sockets = self._conversations.get(conversation_id)
        if sockets is not None:
            sockets.discard(socket)
            if not sockets:
                del self._conversations[conversation_id]

    async def notify(self, request: HandoffRequested) -> None:
        await self.broadcast(
            {
                "type": "handoff_new",
                "handoff": {
                    "handoff_id": None,
                    "conversation_id": request.conversation_id,
                    "status": "open",
                    "reason": request.reason,
                    "priority": request.priority,
                    "summary": request.summary,
                    "created_at": request.requested_at.isoformat(),
                    "claimed_by": None,
                },
            }
        )

    async def forward_customer_message(self, handoff_id: str, text: str) -> None:
        await self.broadcast({"type": "handoff_message", "handoff_id": handoff_id, "text": text})

    async def broadcast(self, event: dict[str, Any]) -> None:
        await self._send_all(self._panel, event)

    async def send_to_conversation(self, message: OutboundMessageReady) -> None:
        with channel_send_span(message.conversation_id, message.channel.value, message.message_id):
            await self._send_all(
                self._conversations.get(message.conversation_id, set()),
                {
                    "type": "message",
                    "message_id": message.message_id,
                    "text": message.text,
                    "source": message.source,
                    "citations": list(message.citations),
                },
            )

    async def send(self, message: OutboundMessageReady) -> None:
        """`ChannelSender` do canal web."""
        await self.send_to_conversation(message)

    @staticmethod
    async def _send_all(sockets: set[JsonSocket], event: dict[str, Any]) -> None:
        for socket in list(sockets):
            try:
                await socket.send_json(event)
            except Exception:
                logger.warning("conexão WebSocket inválida removida")
                sockets.discard(socket)
