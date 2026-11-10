"""Ledger de entregas em memória: compartilhado entre senders simula processos distintos."""

from __future__ import annotations

from commerce_agents.domain.conversation.channel import Channel


class InMemoryDeliveryLedger:
    """Implementa ``DeliveryLedger``; ``marks`` registra cada chamada de ``mark_delivered``."""

    def __init__(self, delivered: dict[str, Channel] | None = None) -> None:
        self._delivered: dict[str, Channel] = dict(delivered or {})
        self.marks: list[tuple[str, Channel]] = []

    async def was_delivered(self, message_id: str) -> bool:
        return message_id in self._delivered

    async def mark_delivered(self, message_id: str, channel: Channel) -> None:
        self.marks.append((message_id, channel))
        self._delivered.setdefault(message_id, channel)
