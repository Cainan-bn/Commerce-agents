"""Itens do pedido (H1c): a loja devolve `items` e as ferramentas de leitura devem entregá-los."""

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from commerce_agents.application.dto.tools import (
    GetOrderStatusOutput,
    ListCustomerOrdersOutput,
    ToolError,
)
from commerce_agents.application.dto.views import OrderView

pytestmark = pytest.mark.unit

_ITEMS = [
    {"sku": "SKU-TENIS-42", "qty": 2, "unit_price_cents": 19990},
    {"sku": "SKU-MEIA-M", "qty": 1, "unit_price_cents": 2990},
]


def _order_body(items: list[dict[str, Any]], order_id: str = "O000001") -> dict[str, Any]:
    return {
        "order_id": order_id,
        "customer_id": "C0001",
        "status": "delivered",
        "created_at": "2026-01-10T12:00:00Z",
        "delivered_at": "2026-01-15T12:00:00Z",
        "tracking_code": "TH100000001BR",
        "total_cents": 42970,
        "items": items,
        "shipping": {"cep": "01310100", "method": "standard", "cost_cents": 1500},
    }


def _client(body: Any) -> httpx.AsyncClient:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    return httpx.AsyncClient(transport=transport, base_url="http://store")


async def _get_order(make_unit_executor: Any, items: list[dict[str, Any]]) -> Any:
    executor = make_unit_executor(client=_client(_order_body(items)))

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, GetOrderStatusOutput), result
    return result


async def test_get_order_status_expoe_os_itens_na_ordem_da_loja(make_unit_executor):
    result = await _get_order(make_unit_executor, _ITEMS)

    assert [(item.sku, item.qty) for item in result.order.items] == [
        ("SKU-TENIS-42", 2),
        ("SKU-MEIA-M", 1),
    ]
    assert {type(item).__name__ for item in result.order.items} == {"OrderItemView"}


async def test_list_customer_orders_expoe_os_itens_de_cada_pedido(make_unit_executor):
    body = [_order_body(_ITEMS, "O000001"), _order_body(_ITEMS[:1], "O000002")]
    executor = make_unit_executor(client=_client(body))

    result = await executor.invoke("Pedidos", "list_customer_orders", {"customer_id": "C0001"})

    assert not isinstance(result, ToolError), result
    assert isinstance(result, ListCustomerOrdersOutput)
    assert [[item.sku for item in order.items] for order in result.orders] == [
        ["SKU-TENIS-42", "SKU-MEIA-M"],
        ["SKU-TENIS-42"],
    ]


async def test_pedido_sem_itens_tem_tupla_vazia(make_unit_executor):
    result = await _get_order(make_unit_executor, [])

    assert result.order.items == ()


async def test_json_entregue_ao_llm_contem_sku_e_quantidade(make_unit_executor):
    from commerce_agents.infrastructure.agents.graph import _render_result

    result = await _get_order(make_unit_executor, _ITEMS)

    rendered = json.loads(_render_result(result))

    assert rendered["order"]["items"] == [
        {"sku": "SKU-TENIS-42", "qty": 2},
        {"sku": "SKU-MEIA-M", "qty": 1},
    ]


def test_order_view_continua_rejeitando_campo_desconhecido():
    with pytest.raises(ValidationError):
        OrderView.model_validate(
            {
                "order_id": "O000001",
                "customer_id": "C0001",
                "status": "paid",
                "tracking_code": None,
                "created_at": "2026-01-10T12:00:00Z",
                "delivered_at": None,
                "total_cents": 1000,
                "campo_desconhecido": 1,
            }
        )


def test_order_item_view_e_estrito_e_rejeita_campo_desconhecido():
    from commerce_agents.application.dto.views import OrderItemView

    assert OrderItemView(sku="SKU-TENIS-42", qty=2).qty == 2
    with pytest.raises(ValidationError):
        OrderItemView.model_validate({"sku": "SKU-TENIS-42", "qty": 2, "unit_price_cents": 1})
