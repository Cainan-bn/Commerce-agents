"""Retries do executor (ADR 0011): leituras repetem transitórios; irreversíveis, no máximo 1."""

import httpx
import pytest
from fastapi import FastAPI

from commerce_agents.application.dto.tools import (
    CancelOrderOutput,
    GetOrderStatusOutput,
    ToolError,
    ToolErrorCode,
)
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import STORE_URL, irreversible_arguments, issue_token

pytestmark = pytest.mark.contract


def _client(
    store_app: FastAPI, *, fail_first: int = 0, fail_status: int = 503, timeout_first: int = 0
) -> tuple[httpx.AsyncClient, RecordingTransport]:
    transport = RecordingTransport(
        httpx.ASGITransport(app=store_app),
        fail_first=fail_first,
        fail_status=fail_status,
        timeout_first=timeout_first,
    )
    return httpx.AsyncClient(transport=transport, base_url=STORE_URL), transport


async def test_leitura_recupera_de_503_intermitente(store_app, make_executor, sleeps):
    client, transport = _client(store_app, fail_first=2, fail_status=503)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, GetOrderStatusOutput)
    assert len(transport.requests) == 3
    assert len(sleeps) == 2


async def test_leitura_esgota_retries_e_devolve_retryable(store_app, make_executor, sleeps):
    client, transport = _client(store_app, fail_first=10, fail_status=503)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True
    assert len(transport.requests) == 3  # 1 tentativa + max_retries=2
    assert len(sleeps) == 2


async def test_backoff_cresce_exponencialmente(store_app, make_executor, sleeps):
    client, _ = _client(store_app, fail_first=10, fail_status=503)
    executor = make_executor(client=client)

    await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert sleeps[0] > 0
    assert sleeps[1] > sleeps[0]


async def test_timeout_de_leitura_repete_e_devolve_upstream_timeout(
    store_app, make_executor, sleeps
):
    client, transport = _client(store_app, timeout_first=10)
    executor = make_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_TIMEOUT
    assert len(transport.requests) == 3


async def test_erro_nao_retryable_nao_repete(make_executor, transport: RecordingTransport, sleeps):
    executor = make_executor()

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O999999"})

    assert isinstance(result, ToolError)
    assert len(transport.requests) == 1
    assert sleeps == []


async def test_irreversivel_faz_no_maximo_um_retry_com_a_mesma_chave(
    store_app, make_executor, tokens: InMemoryTokenStore, sleeps
):
    client, transport = _client(store_app, fail_first=10, fail_status=503)
    executor = make_executor(client=client)
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})

    result = await executor.invoke(
        "Pedidos",
        "cancel_order",
        irreversible_arguments("cancel_order", token, "idem-retry-0001", order_id="O000014"),
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True
    assert len(transport.requests) == 2  # max_retries=1
    keys = {request.headers["Idempotency-Key"] for request in transport.requests}
    assert keys == {"idem-retry-0001"}
    assert len(sleeps) == 1


async def test_irreversivel_recupera_com_a_mesma_chave_sem_novo_token(
    store_app, make_executor, tokens: InMemoryTokenStore, sleeps
):
    client, transport = _client(store_app, fail_first=1, fail_status=503)
    executor = make_executor(client=client)
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})

    result = await executor.invoke(
        "Pedidos",
        "cancel_order",
        irreversible_arguments("cancel_order", token, "idem-retry-0002", order_id="O000014"),
    )

    assert isinstance(result, CancelOrderOutput)
    assert len(transport.requests) == 2
    assert {request.headers["Idempotency-Key"] for request in transport.requests} == {
        "idem-retry-0002"
    }
    assert store_app.state.store.orders["O000014"].status == "cancelled"
