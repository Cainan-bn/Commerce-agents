"""Adaptadores em memória dos ports de confirmação e idempotência (apenas processo único).

Servem ao ``python -m commerce_agents.infrastructure.mcp`` em desenvolvimento. Em produção os
ports são implementados sobre armazenamento compartilhado (o token é emitido pelo orquestrador).
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Issued:
    binding: tuple[str, str, str]
    expires_at: float
    used: bool = False


class InMemoryTokenStore:
    """Tokens de uso único, com expiração e vínculo a conversa, ação e digest."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tokens: dict[str, _Issued] = {}

    async def issue(
        self, conversation_id: str, action: str, arguments_digest: str, ttl_seconds: int
    ) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = _Issued(
            (conversation_id, action, arguments_digest), self._clock() + ttl_seconds
        )
        return token

    async def consume(
        self, token: str, conversation_id: str, action: str, arguments_digest: str
    ) -> bool:
        issued = self._tokens.get(token)
        if issued is None or issued.used or self._clock() >= issued.expires_at:
            return False
        if issued.binding != (conversation_id, action, arguments_digest):
            return False
        issued.used = True
        return True


class InMemoryIdempotencyRegistry:
    """Resultado por ``idempotency_key`` com o fingerprint dos argumentos de ação."""

    def __init__(self) -> None:
        self._results: dict[str, tuple[str, str]] = {}

    async def get(self, key: str) -> tuple[str, str] | None:
        return self._results.get(key)

    async def put(self, key: str, fingerprint: str, result_json: str) -> None:
        self._results[key] = (fingerprint, result_json)
