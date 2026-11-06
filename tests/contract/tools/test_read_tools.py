"""Ferramentas de leitura contra o mock_store com pedidos e produtos reais do seed."""

import pytest

from commerce_agents.application.dto.tools import (
    OUTPUT_MODELS,
    CheckAvailabilityOutput,
    CheckReturnEligibilityOutput,
    GetOrderStatusOutput,
    ListCustomerOrdersOutput,
    QuoteShippingOutput,
    SearchProductsOutput,
    ToolError,
    ToolErrorCode,
)
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import AGENT_FOR_TOOL, READ_TOOLS, SAMPLE_ARGUMENTS, read_seed

pytestmark = pytest.mark.contract

INVALID_ARGUMENTS: list[tuple[str, dict[str, object]]] = [
    ("get_order_status", {"order_id": "O1"}),
    ("get_order_status", {"order_id": "P0001"}),
    ("list_customer_orders", {"customer_id": "C1"}),
    ("list_customer_orders", {"customer_id": "C0001", "limit": 0}),
    ("search_products", {"query": ""}),
    ("check_availability", {"product_id": "P01"}),
    ("quote_shipping", {"cep": "123", "items": [{"sku": "P0168-GG-AZUL", "qty": 1}]}),
    ("quote_shipping", {"cep": "76169-162", "items": []}),
    ("check_return_eligibility", {"order_id": "O000001", "sku": "X"}),
]


@pytest.mark.parametrize("tool_name", READ_TOOLS)
async def test_saida_valida_contra_o_output_model(make_executor, tool_name):
    executor = make_executor()

    result = await executor.invoke(
        AGENT_FOR_TOOL[tool_name], tool_name, SAMPLE_ARGUMENTS[tool_name]
    )

    output_model = OUTPUT_MODELS[tool_name]
    assert isinstance(result, output_model)
    assert output_model.model_validate(result.model_dump()) == result


async def test_get_order_status_devolve_pedido_entregue_do_seed(make_executor):
    executor = make_executor()

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, GetOrderStatusOutput)
    assert result.order.order_id == "O000001"
    assert result.order.status == "delivered"
    assert result.order.delivered_at is not None


async def test_list_customer_orders_devolve_pedidos_do_cliente(make_executor):
    executor = make_executor()
    customer_orders = [o for o in read_seed("orders.jsonl") if o["customer_id"] == "C0053"]

    result = await executor.invoke("Pedidos", "list_customer_orders", {"customer_id": "C0053"})

    assert isinstance(result, ListCustomerOrdersOutput)
    assert len(result.orders) == min(5, len(customer_orders))
    assert {order.customer_id for order in result.orders} == {"C0053"}
    assert {order.order_id for order in result.orders} <= {o["order_id"] for o in customer_orders}


async def test_search_products_encontra_produtos_pelo_nome(make_executor):
    executor = make_executor()

    result = await executor.invoke("CatalogoVendas", "search_products", {"query": "tênis"})

    assert isinstance(result, SearchProductsOutput)
    assert "P0001" in {product.product_id for product in result.products}
    assert all("tênis" in product.name.lower() for product in result.products)


async def test_check_availability_reflete_estoque_do_seed(make_executor):
    executor = make_executor()
    product = next(p for p in read_seed("products.jsonl") if p["product_id"] == "P0001")
    expected_available = any(variant["stock"] > 0 for variant in product["variants"])

    result = await executor.invoke("CatalogoVendas", "check_availability", {"product_id": "P0001"})

    assert isinstance(result, CheckAvailabilityOutput)
    assert result.available is expected_available
    assert len(result.variants) == len(product["variants"])


async def test_quote_shipping_usa_faixa_do_cep_e_flag_de_frete_gratis(make_executor):
    executor = make_executor()

    result = await executor.invoke(
        "CatalogoVendas", "quote_shipping", SAMPLE_ARGUMENTS["quote_shipping"]
    )

    assert isinstance(result, QuoteShippingOutput)
    assert result.price_cents in (0, 3990)  # faixa do CEP começando em 7 (ou frete grátis)
    assert result.eta_days == 5
    assert result.free_shipping is (result.price_cents == 0)


async def test_check_return_eligibility_dentro_do_prazo(make_executor):
    executor = make_executor()

    result = await executor.invoke(
        "PosVenda", "check_return_eligibility", {"order_id": "O000001", "sku": "P0168-GG-AZUL"}
    )

    assert isinstance(result, CheckReturnEligibilityOutput)
    assert result.eligible is True
    assert result.reason == "ok"
    assert result.deadline is not None


async def test_check_return_eligibility_prazo_vencido(make_executor):
    executor = make_executor()

    result = await executor.invoke(
        "PosVenda", "check_return_eligibility", {"order_id": "O000004", "sku": "P0056-45-MARROM"}
    )

    assert isinstance(result, CheckReturnEligibilityOutput)
    assert result.eligible is False
    assert result.reason == "deadline_exceeded"


@pytest.mark.parametrize(("tool_name", "bad_arguments"), INVALID_ARGUMENTS)
async def test_argumento_invalido_nao_chama_a_loja(
    make_executor, transport: RecordingTransport, tool_name, bad_arguments
):
    executor = make_executor()

    result = await executor.invoke(AGENT_FOR_TOOL[tool_name], tool_name, bad_arguments)

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.INVALID_ARGUMENT
    assert result.retryable is False
    assert transport.requests == []


@pytest.mark.parametrize("tool_name", READ_TOOLS)
async def test_campo_extra_gera_invalid_argument_sem_chamar_a_loja(
    make_executor, transport: RecordingTransport, tool_name
):
    executor = make_executor()
    arguments = {**SAMPLE_ARGUMENTS[tool_name], "campo_extra": "x"}

    result = await executor.invoke(AGENT_FOR_TOOL[tool_name], tool_name, arguments)

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.INVALID_ARGUMENT
    assert transport.requests == []
