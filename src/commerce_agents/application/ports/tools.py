"""Port de execução de ferramentas usado pelos casos de uso e pelo orquestrador."""

from collections.abc import Mapping
from typing import Any, Protocol

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.tools import ToolError


class ToolInvoker(Protocol):
    """Executa uma ferramenta já validada pela allowlist; nunca lança.

    Devolve o Output model da ferramenta (`ok=True`) ou `ToolError`.
    """

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> StrictModel | ToolError: ...
