"""Casos de uso de confirmação de ações irreversíveis (ADR 0008 e 0011).

O LLM só propõe; quem emite o token, interpreta o "sim" do cliente e dispara a ferramenta é
código determinístico. A resposta do cliente nunca é interpretada por modelo.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from commerce_agents.application.dto.confirmation import (
    ConfirmationOutcome,
    ConfirmationStatus,
    PendingAction,
    Reply,
)
from commerce_agents.application.dto.events import IrreversibleActionConfirmed
from commerce_agents.application.dto.tools import (
    INPUT_MODELS,
    TOOL_SPECS,
    ToolError,
    action_digest,
)
from commerce_agents.application.ports.confirmation import ConfirmationTokenStore
from commerce_agents.application.ports.tools import ToolInvoker

Clock = Callable[[], datetime]
Publish = Callable[[IrreversibleActionConfirmed], Awaitable[None]]

DEFAULT_TTL_SECONDS = 300

_MAX_AFFIRMATIVE_WORDS = 4
_MAX_NEGATIVE_WORDS = 6
# Vocabulário fechado: qualquer palavra fora dele (inclusive tentativas de instrução) torna a
# resposta ambígua. A afirmativa exige ainda uma palavra de consentimento explícito.
_CONSENT_WORDS = frozenset({"sim", "confirmo", "confirmar", "confirmado", "pode", "claro"})
_FILLER_WORDS = frozenset({"cancelar", "cancele", "devolver", "devolva", "quero", "com", "certeza"})
_NEGATION_WORDS = frozenset({"nao", "nunca", "jamais", "nem", "desisti", "desisto", "esquece"})
_NEGATIVE_PHRASES = ("deixa pra la",)

_SUMMARIES: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "cancel_order": lambda a: f"Vou cancelar o pedido {a['order_id']}.",
    "open_return": lambda a: (
        f"Vou abrir a devolução do item {a['sku']} do pedido {a['order_id']} "
        f"(motivo: {a['reason']})."
    ),
}


def _words(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", stripped).split()


def classify_reply(text: str) -> Reply:
    """Classifica a resposta do cliente; na dúvida, ``UNCLEAR``."""
    words = _words(text)
    if not words:
        return Reply.UNCLEAR
    has_consent = any(word in _CONSENT_WORDS for word in words)
    has_negation = any(word in _NEGATION_WORDS for word in words) or any(
        phrase in " ".join(words) for phrase in _NEGATIVE_PHRASES
    )
    if has_consent and has_negation:
        return Reply.UNCLEAR
    if has_negation:
        return Reply.NEGATIVE if len(words) <= _MAX_NEGATIVE_WORDS else Reply.UNCLEAR
    vocabulary = _CONSENT_WORDS | _FILLER_WORDS
    if has_consent and len(words) <= _MAX_AFFIRMATIVE_WORDS and all(w in vocabulary for w in words):
        return Reply.AFFIRMATIVE
    return Reply.UNCLEAR


class ProposeIrreversibleAction:
    """Valida a proposta do agente e emite o token de confirmação vinculado aos argumentos."""

    def __init__(
        self,
        tokens: ConfirmationTokenStore,
        *,
        clock: Clock,
        new_key: Callable[[], str],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._tokens = tokens
        self._clock = clock
        self._new_key = new_key
        self._ttl_seconds = ttl_seconds

    async def execute(
        self,
        conversation_id: str,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> PendingAction:
        spec = TOOL_SPECS.get(tool_name)
        if spec is None or not spec.irreversible:
            raise ValueError(f"A ferramenta {tool_name} não é irreversível.")
        key = self._new_key()
        action_arguments = {
            name: arguments[name] for name in spec.action_fields if name in arguments
        }
        try:
            validated = INPUT_MODELS[tool_name].model_validate(
                {
                    **action_arguments,
                    "conversation_id": conversation_id,
                    "confirmation_token": "pendente",
                    "idempotency_key": key,
                },
                strict=False,
            )
        except ValidationError as error:
            raise ValueError(f"Argumentos inválidos para {tool_name}.") from error
        action_arguments = {name: getattr(validated, name) for name in spec.action_fields}
        token = await self._tokens.issue(
            conversation_id,
            tool_name,
            action_digest(tool_name, action_arguments),
            self._ttl_seconds,
        )
        summary = (
            f"{_SUMMARIES[tool_name](action_arguments)} "
            "Esta ação não pode ser desfeita. Você confirma?"
        )
        return PendingAction(
            conversation_id=conversation_id,
            agent=agent,
            tool_name=tool_name,
            arguments=action_arguments,
            confirmation_token=token,
            idempotency_key=key,
            summary=summary,
            expires_at=self._clock() + timedelta(seconds=self._ttl_seconds),
        )


class ConfirmIrreversibleAction:
    """Interpreta a resposta do cliente e, só se afirmativa, executa a proposta pendente."""

    def __init__(self, invoker: ToolInvoker, publish: Publish, *, clock: Clock) -> None:
        self._invoker = invoker
        self._publish = publish
        self._clock = clock

    async def execute(self, pending: PendingAction, customer_reply: str) -> ConfirmationOutcome:
        now = self._clock()
        if now >= pending.expires_at:
            return ConfirmationOutcome(status=ConfirmationStatus.EXPIRED)
        reply = classify_reply(customer_reply)
        if reply is Reply.NEGATIVE:
            return ConfirmationOutcome(status=ConfirmationStatus.DECLINED)
        if reply is Reply.UNCLEAR:
            return ConfirmationOutcome(status=ConfirmationStatus.UNCLEAR)
        await self._publish(
            IrreversibleActionConfirmed(
                conversation_id=pending.conversation_id,
                action=pending.tool_name,
                idempotency_key=pending.idempotency_key,
                confirmation_token_id=hashlib.sha256(
                    pending.confirmation_token.encode()
                ).hexdigest()[:16],
                confirmed_at=now,
            )
        )
        result = await self._invoker.invoke(
            pending.agent,
            pending.tool_name,
            {
                **pending.arguments,
                "conversation_id": pending.conversation_id,
                "confirmation_token": pending.confirmation_token,
                "idempotency_key": pending.idempotency_key,
            },
            conversation_id=pending.conversation_id,
        )
        if isinstance(result, ToolError):
            return ConfirmationOutcome(status=ConfirmationStatus.FAILED, error=result)
        return ConfirmationOutcome(status=ConfirmationStatus.EXECUTED, result=result)
