"""Mapeamento de erros HTTP da loja para ToolErrorCode (docs/architecture/tools.md)."""

import httpx
import pytest

from commerce_agents.application.dto.tools import ToolError, ToolErrorCode
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import MOCK_TODAY, STORE_URL

pytestmark = pytest.mark.contract


async def test_404_em_leitura_vira_not_found_sem_retry(
    make_executor, transport: RecordingTransport
):
    executor = make_executor()

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O999999"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND
    assert result.retryable is False
    assert len(transport.requests) == 1


async def test_sku_fora_do_pedido_vira_not_found(make_executor):
    executor = make_executor()

    result = await executor.invoke(
        "PosVenda", "check_return_eligibility", {"order_id": "O000001", "sku": "P0056-45-MARROM"}
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND


async def test_422_demais_vira_invalid_argument(make_executor, transport: RecordingTransport):
    executor = make_executor()

    result = await executor.invoke(
        "CatalogoVendas",
        "quote_shipping",
        {"cep": "76169-162", "items": [{"sku": "SKU-DESCONHECIDO", "qty": 1}]},
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.INVALID_ARGUMENT
    assert result.retryable is False
    assert len(transport.requests) == 1


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_5xx_de_gateway_vira_upstream_unavailable_retryable(
    store_app, make_executor, status: int
):
    transport = RecordingTransport(
        httpx.ASGITransport(app=store_app), fail_first=10, fail_status=status
    )
    client = httpx.AsyncClient(transport=transport, base_url=STORE_URL)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True


async def test_500_vira_upstream_error_nao_retryable(store_app, make_executor):
    transport = RecordingTransport(
        httpx.ASGITransport(app=store_app), fail_first=10, fail_status=500
    )
    client = httpx.AsyncClient(transport=transport, base_url=STORE_URL)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_ERROR
    assert result.retryable is False
    assert len(transport.requests) == 1


async def test_4xx_fora_da_tabela_vira_upstream_error(store_app, make_executor):
    transport = RecordingTransport(
        httpx.ASGITransport(app=store_app), fail_first=10, fail_status=401
    )
    client = httpx.AsyncClient(transport=transport, base_url=STORE_URL)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_ERROR


async def test_timeout_simulado_vira_upstream_timeout_retryable(store_app, make_executor):
    transport = RecordingTransport(httpx.ASGITransport(app=store_app), timeout_first=10)
    client = httpx.AsyncClient(transport=transport, base_url=STORE_URL)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_TIMEOUT
    assert result.retryable is True


async def test_timeout_real_por_delay_do_mock_store_vira_upstream_timeout(store_app, make_executor):
    # Latência injetada no mock (X-Mock-Delay-Ms) maior que o timeout de 3s da leitura.
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=store_app),
        base_url=STORE_URL,
        headers={"X-Mock-Delay-Ms": "3500"},
    )
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_TIMEOUT


async def test_erro_nunca_expoe_corpo_bruto_nem_url(store_app, make_executor):
    transport = RecordingTransport(
        httpx.ASGITransport(app=store_app), fail_first=10, fail_status=500
    )
    client = httpx.AsyncClient(transport=transport, base_url=STORE_URL)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert "falha injetada" not in result.message
    assert "http" not in result.message.lower()
    assert MOCK_TODAY not in result.message
