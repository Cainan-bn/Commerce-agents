"""ToolInvoker escopado ao cliente do turno (ADR 0013): identidade e posse só em código."""

from collections.abc import Mapping
from typing import Any

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.tools import (
    GetOrderStatusOutput,
    ToolError,
    ToolErrorCode,
)
from commerce_agents.application.ports.tools import ToolInvoker

_OWNERSHIP_CHECKED = frozenset(
    {"get_order_status", "check_return_eligibility", "cancel_order", "open_return"}
)
# Agente usado só para a leitura de posse: sua allowlist contém `get_order_status`.
_READER_AGENT = "Pedidos"


# Loja fora do ar ou lenta: propagado (igual para qualquer pedido, não revela o dono).
_UPSTREAM_ERRORS = frozenset(
    {
        ToolErrorCode.UPSTREAM_TIMEOUT,
        ToolErrorCode.UPSTREAM_UNAVAILABLE,
        ToolErrorCode.UPSTREAM_ERROR,
    }
)


def _not_found() -> ToolError:
    # Mesma resposta para pedido inexistente, de outro cliente ou leitura inválida.
    return ToolError(code=ToolErrorCode.NOT_FOUND, message="pedido não encontrado")


class ScopedToolInvoker:
    """Implementa `ToolInvoker`: força o `customer_id` e confere a posse do pedido."""

    def __init__(self, inner: ToolInvoker, customer_id: str) -> None:
        self._inner = inner
        self._customer_id = customer_id

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> StrictModel | ToolError:
        args = dict(arguments)
        if tool_name == "list_customer_orders":
            args["customer_id"] = self._customer_id
        elif tool_name in _OWNERSHIP_CHECKED and isinstance(args.get("order_id"), str):
            denied = await self._check_ownership(args["order_id"])
            if denied is not None:
                return denied
        return await self._inner.invoke(agent, tool_name, args, conversation_id=conversation_id)

    async def _check_ownership(self, order_id: str) -> ToolError | None:
        """`None` se o pedido é do cliente; senão o erro a devolver no lugar da ferramenta."""
        result = await self._inner.invoke(_READER_AGENT, "get_order_status", {"order_id": order_id})
        if isinstance(result, ToolError) and result.code in _UPSTREAM_ERRORS:
            return result
        if isinstance(result, GetOrderStatusOutput) and (
            result.order.customer_id == self._customer_id
        ):
            return None
        return _not_found()
