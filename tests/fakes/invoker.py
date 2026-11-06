"""Fakes do ToolInvoker e do publicador de eventos, com registro de ordem de chamadas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


class FakeToolInvoker:
    """Registra cada invocação e devolve o `outcome` configurado (Output ou ToolError)."""

    def __init__(
        self, outcome: BaseModel | None = None, log: list[tuple[str, str]] | None = None
    ) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self._log = log

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "agent": agent,
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "conversation_id": conversation_id,
            }
        )
        if self._log is not None:
            self._log.append(("tool", tool_name))
        return self.outcome


class RecordingPublisher:
    """Guarda os eventos publicados e, opcionalmente, registra a ordem no log compartilhado."""

    def __init__(self, log: list[tuple[str, str]] | None = None) -> None:
        self.events: list[Any] = []
        self._log = log

    async def __call__(self, event: Any) -> None:
        self.events.append(event)
        if self._log is not None:
            self._log.append(("event", getattr(event, "action", "")))
