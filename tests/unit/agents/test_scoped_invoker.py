"""ScopedToolInvoker (ADR 0013): customer_id do escopo, posse de pedido, sem vazar existência."""

from typing import Any

import pytest

from commerce_agents.application.dto.tools import (
    CancelOrderOutput,
    GetOrderStatusOutput,
    ListCustomerOrdersOutput,
    ToolError,
    ToolErrorCode,
)
from commerce_agents.application.dto.views import OrderView
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit

OWNER = "C0053"
OTHER = "C0001"


def _order(order_id: str, customer_id: str) -> OrderView:
    return OrderView(
        order_id=order_id,
        customer_id=customer_id,
        status="paid",
        tracking_code=None,
        created_at=BASE_TIME,
        delivered_at=None,
        total_cents=1000,
    )


class FakeInner:
    """ToolInvoker fake: registra chamadas e responde por ferramenta com um mapa configurável."""

    def __init__(self, orders: dict[str, OrderView], read_error: ToolError | None = None) -> None:
        self.orders = orders
        self.read_error = read_error
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(
        self, agent: str, tool_name: str, arguments: Any, *, conversation_id: Any = None
    ) -> Any:
        self.calls.append((agent, tool_name, dict(arguments)))
        if tool_name == "get_order_status":
            if self.read_error is not None:
                return self.read_error
            order = self.orders.get(arguments["order_id"])
            if order is None:
                return ToolError(code=ToolErrorCode.NOT_FOUND, message="pedido não encontrado")
            return GetOrderStatusOutput(order=order)
        if tool_name == "list_customer_orders":
            return ListCustomerOrdersOutput(orders=())
        if tool_name == "cancel_order":
            return CancelOrderOutput(
                order_id=arguments["order_id"], status="cancelled", cancelled_at=BASE_TIME
            )
        return ToolError(code=ToolErrorCode.NOT_FOUND, message="não tratado no fake")


def _scoped(inner: FakeInner, customer_id: str = OWNER):  # type: ignore[no-untyped-def]
    from commerce_agents.application.agents.scoped_invoker import ScopedToolInvoker

    return ScopedToolInvoker(inner, customer_id=customer_id)


def _real_calls(inner: FakeInner, tool: str) -> list[tuple[str, str, dict[str, Any]]]:
    return [call for call in inner.calls if call[1] == tool]


async def test_list_customer_orders_forca_o_customer_id_do_escopo():
    inner = FakeInner(orders={})
    scoped = _scoped(inner)

    await scoped.invoke("Pedidos", "list_customer_orders", {"customer_id": OTHER})

    assert _real_calls(inner, "list_customer_orders")[0][2]["customer_id"] == OWNER


async def test_pedido_proprio_passa_para_a_ferramenta():
    inner = FakeInner(orders={"O000001": _order("O000001", OWNER)})
    scoped = _scoped(inner)

    result = await scoped.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, GetOrderStatusOutput)
    assert result.order.order_id == "O000001"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_order_status", {"order_id": "O000002"}),
        ("cancel_order", {"order_id": "O000002"}),
    ],
)
async def test_pedido_de_outro_cliente_vira_not_found_sem_chamar_a_ferramenta(
    tool: str, arguments: dict[str, Any]
):
    inner = FakeInner(orders={"O000002": _order("O000002", OTHER)})
    scoped = _scoped(inner)

    result = await scoped.invoke("Pedidos", tool, arguments)

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND
    assert _real_calls(inner, "cancel_order") == []
    if tool == "cancel_order":
        assert _real_calls(inner, "cancel_order") == []


async def test_check_return_e_open_return_checam_posse_antes_de_agir():
    inner = FakeInner(orders={"O000003": _order("O000003", OTHER)})
    scoped = _scoped(inner)

    result = await scoped.invoke(
        "PosVenda", "open_return", {"order_id": "O000003", "sku": "P0168-GG-AZUL", "reason": "x"}
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND
    assert _real_calls(inner, "open_return") == []


async def test_pedido_inexistente_e_de_outro_cliente_sao_indistinguiveis():
    inner = FakeInner(orders={"O000002": _order("O000002", OTHER)})
    scoped = _scoped(inner)

    other = await scoped.invoke("Pedidos", "get_order_status", {"order_id": "O000002"})
    missing = await scoped.invoke("Pedidos", "get_order_status", {"order_id": "O999999"})

    assert isinstance(other, ToolError) and isinstance(missing, ToolError)
    assert (other.code, other.message) == (missing.code, missing.message)


async def test_falha_na_leitura_de_posse_vira_not_found():
    inner = FakeInner(
        orders={},
        read_error=ToolError(code=ToolErrorCode.UPSTREAM_UNAVAILABLE, message="loja fora"),
    )
    scoped = _scoped(inner)

    result = await scoped.invoke(
        "Pedidos",
        "cancel_order",
        {
            "order_id": "O000014",
            "conversation_id": "c",
            "confirmation_token": "t",
            "idempotency_key": "idem-escopo-01",
        },
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND
    assert _real_calls(inner, "cancel_order") == []
