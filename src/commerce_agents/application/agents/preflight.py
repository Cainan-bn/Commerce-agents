"""Pré-checagem de viabilidade antes de propor ação irreversível (ADR 0013).

Roda pelo `ScopedToolInvoker` (posse incluída) e não emite token: se a ação não é viável, o
`ToolError` volta ao LLM como resultado de ferramenta e nada é proposto ao cliente.
"""

from collections.abc import Mapping
from typing import Any

from commerce_agents.application.dto.tools import (
    CheckReturnEligibilityOutput,
    GetOrderStatusOutput,
    ToolError,
    ToolErrorCode,
)
from commerce_agents.application.ports.tools import ToolInvoker
from commerce_agents.domain.order.order import CANCELABLE_STATUSES
from commerce_agents.domain.order.status import OrderStatus

# Já saiu da loja: não cancela, mas a devolução resolve depois da entrega.
_RETURNABLE_STATUSES = frozenset(
    {OrderStatus.shipped, OrderStatus.in_transit, OrderStatus.delivered}
)


async def preflight_irreversible(
    invoker: ToolInvoker,
    agent: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    conversation_id: str,
) -> ToolError | None:
    """`None` se a ação pode ser proposta; senão o `ToolError` a devolver ao LLM."""
    if tool_name == "cancel_order":
        return await _cancelable(invoker, agent, arguments, conversation_id)
    if tool_name == "open_return":
        return await _eligible(invoker, agent, arguments, conversation_id)
    return None


async def _cancelable(
    invoker: ToolInvoker, agent: str, arguments: Mapping[str, Any], conversation_id: str
) -> ToolError | None:
    result = await invoker.invoke(
        agent,
        "get_order_status",
        {"order_id": arguments.get("order_id")},
        conversation_id=conversation_id,
    )
    if isinstance(result, ToolError):
        return result
    if not isinstance(result, GetOrderStatusOutput):
        return ToolError(code=ToolErrorCode.UPSTREAM_ERROR, message="resposta inesperada da loja")
    status = OrderStatus(result.order.status)
    if status not in CANCELABLE_STATUSES:
        return ToolError(
            code=ToolErrorCode.NOT_CANCELABLE,
            message=_not_cancelable_message(status, result.order.tracking_code),
        )
    return None


def _not_cancelable_message(status: OrderStatus, tracking_code: str | None) -> str:
    message = "Este pedido não pode mais ser cancelado pelo status atual."
    if status not in _RETURNABLE_STATUSES:
        return message
    if status is OrderStatus.delivered:
        message += " O cliente já recebeu o pedido e pode pedir a devolução."
    else:
        message += " Depois de receber o pedido, o cliente pode pedir a devolução."
    if tracking_code:
        message += f" Código de rastreio: {tracking_code}."
    return message


async def _eligible(
    invoker: ToolInvoker, agent: str, arguments: Mapping[str, Any], conversation_id: str
) -> ToolError | None:
    result = await invoker.invoke(
        agent,
        "check_return_eligibility",
        {"order_id": arguments.get("order_id"), "sku": arguments.get("sku")},
        conversation_id=conversation_id,
    )
    if isinstance(result, ToolError):
        return result
    if not isinstance(result, CheckReturnEligibilityOutput):
        return ToolError(code=ToolErrorCode.UPSTREAM_ERROR, message="resposta inesperada da loja")
    if not result.eligible:
        return ToolError(
            code=ToolErrorCode.NOT_ELIGIBLE,
            message=f"Item não elegível para devolução: {result.reason}.",
        )
    return None
