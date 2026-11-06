"""Entrega de mensagens aos canais (Graph API da Meta) com retry só para falhas transitórias."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping

import httpx

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.application.ports.channels import ChannelSender
from commerce_agents.domain.conversation.channel import Channel

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v21.0"
_MAX_ATTEMPTS = 3
_SEEN_LIMIT = 10_000
Sleep = Callable[[float], Awaitable[None]]


class SendRejectedError(Exception):
    """O canal recusou a mensagem (4xx): repetir não adianta."""


class _GraphSender:
    def __init__(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._token = access_token
        self._sleep = sleep
        self._delivered: OrderedDict[str, None] = OrderedDict()

    def _request(self, message: OutboundMessageReady) -> tuple[str, dict[str, object]]:
        raise NotImplementedError

    async def send(self, message: OutboundMessageReady) -> None:
        """Idempotente por `message_id` dentro do processo; 5xx/timeout repetem, 4xx não."""
        if message.message_id in self._delivered:
            return
        url, body = self._request(message)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(
                    url, json=body, headers={"Authorization": f"Bearer {self._token}"}
                )
            except httpx.TransportError:
                response = None
            if response is not None and response.is_success:
                self._remember(message.message_id)
                return
            if response is not None and response.status_code < 500:
                raise SendRejectedError(f"canal recusou a mensagem ({response.status_code})")
            if attempt == _MAX_ATTEMPTS:
                raise ConnectionError("canal indisponível após novas tentativas")
            await self._sleep(2 ** (attempt - 1))

    def _remember(self, message_id: str) -> None:
        self._delivered[message_id] = None
        while len(self._delivered) > _SEEN_LIMIT:
            self._delivered.popitem(last=False)


class WhatsAppSender(_GraphSender):
    def __init__(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        phone_number_id: str,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(client, access_token, sleep=sleep)
        self._url = f"{GRAPH_URL}/{phone_number_id}/messages"

    def _request(self, message: OutboundMessageReady) -> tuple[str, dict[str, object]]:
        return self._url, {
            "messaging_product": "whatsapp",
            "to": message.recipient_external_id,
            "type": "text",
            "text": {"body": message.text},
        }


class InstagramSender(_GraphSender):
    def _request(self, message: OutboundMessageReady) -> tuple[str, dict[str, object]]:
        return f"{GRAPH_URL}/me/messages", {
            "recipient": {"id": message.recipient_external_id},
            "message": {"text": message.text},
        }


class ChannelRouter:
    """Escolhe o `ChannelSender` pelo canal da mensagem."""

    def __init__(self, senders: Mapping[Channel, ChannelSender]) -> None:
        self._senders = dict(senders)

    async def send(self, message: OutboundMessageReady) -> None:
        sender = self._senders.get(message.channel)
        if sender is None:
            logger.error("sem sender para o canal %s", message.channel.value)
            return
        await sender.send(message)
