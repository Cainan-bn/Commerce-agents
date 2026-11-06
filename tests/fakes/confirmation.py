"""Fakes em memória dos ports de confirmação e idempotência (ADR 0008 e 0011)."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _IssuedToken:
    conversation_id: str
    action: str
    arguments_digest: str
    expires_at: float
    used: bool = False


class InMemoryTokenStore:
    """Tokens de uso único, com expiração e vínculo a conversa, ação e digest dos argumentos."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tokens: dict[str, _IssuedToken] = {}

    async def issue(
        self, conversation_id: str, action: str, arguments_digest: str, ttl_seconds: int
    ) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = _IssuedToken(
            conversation_id=conversation_id,
            action=action,
            arguments_digest=arguments_digest,
            expires_at=self._clock() + ttl_seconds,
        )
        return token

    async def consume(
        self, token: str, conversation_id: str, action: str, arguments_digest: str
    ) -> bool:
        record = self._tokens.get(token)
        if record is None or record.used or self._clock() >= record.expires_at:
            return False
        binding = (record.conversation_id, record.action, record.arguments_digest)
        if binding != (conversation_id, action, arguments_digest):
            return False
        record.used = True
        return True


class InMemoryIdempotencyRegistry:
    """Resultado registrado por `idempotency_key`, com o fingerprint dos argumentos de ação."""

    def __init__(self) -> None:
        self._results: dict[str, tuple[str, str]] = {}

    async def get(self, key: str) -> tuple[str, str] | None:
        return self._results.get(key)

    async def put(self, key: str, fingerprint: str, result_json: str) -> None:
        self._results[key] = (fingerprint, result_json)
