"""Testes de contrato da API fake da loja (mock_store)."""

import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from mock_store.main import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ENV_VARS = (
    "DATA_DIR",
    "MOCK_LATENCY_MS",
    "MOCK_ERROR_RATE",
    "MOCK_SEED",
    "MOCK_TODAY",
)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return create_app(FIXTURES_DIR)


@pytest.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://mock") as http_client:
        yield http_client


async def _make_client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://mock")


@pytest.mark.contract
async def test_get_order_returns_order_and_404(client: AsyncClient) -> None:
    response = await client.get("/orders/O000001")

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == "O000001"
    assert body["status"] == "delivered"
    assert body["items"][0]["sku"] == "P0001-42-PRETO"

    missing = await client.get("/orders/O999999")
    assert missing.status_code == 404


@pytest.mark.contract
async def test_customer_orders_sorted_most_recent_first(client: AsyncClient) -> None:
    response = await client.get("/customers/C0001/orders")

    assert response.status_code == 200
    created = [order["created_at"] for order in response.json()]
    assert created == sorted(created, reverse=True)
    assert response.json()[0]["order_id"] == "O000004"

    missing = await client.get("/customers/C999999/orders")
    assert missing.status_code == 404


@pytest.mark.contract
async def test_product_search_name_brand_category_and_limit(client: AsyncClient) -> None:
    by_name = await client.get("/products", params={"query": "urban"})
    assert [p["product_id"] for p in by_name.json()] == ["P0001"]

    by_brand = await client.get("/products", params={"query": "alfa"})
    assert [p["product_id"] for p in by_brand.json()] == ["P0002"]

    by_category = await client.get("/products", params={"query": "calcas"})
    assert [p["product_id"] for p in by_category.json()] == ["P0003"]

    limited = await client.get("/products", params={"query": "", "limit": 2})
    assert len(limited.json()) == 2


@pytest.mark.contract
async def test_get_product_and_404(client: AsyncClient) -> None:
    response = await client.get("/products/P0001")

    assert response.status_code == 200
    assert response.json()["brand"] == "Voltz"

    missing = await client.get("/products/P9999")
    assert missing.status_code == 404


@pytest.mark.contract
async def test_product_availability_filters_by_size_and_color(client: AsyncClient) -> None:
    available = await client.get("/products/P0001/availability", params={"size": "42"})
    assert available.status_code == 200
    body = available.json()
    assert body["available"] is True
    assert [v["sku"] for v in body["variants"]] == ["P0001-42-PRETO"]

    unavailable = await client.get("/products/P0001/availability", params={"size": "40"})
    assert unavailable.json()["available"] is False

    by_color = await client.get("/products/P0001/availability", params={"color": "preto"})
    assert len(by_color.json()["variants"]) == 2

    missing = await client.get("/products/P9999/availability")
    assert missing.status_code == 404


@pytest.mark.contract
async def test_shipping_quote_is_deterministic_and_free_above_threshold(
    client: AsyncClient,
) -> None:
    payload = {"cep": "01000-000", "items": [{"sku": "P0002-M-BRANCO", "qty": 1}]}

    first = await client.post("/shipping/quote", json=payload)
    second = await client.post("/shipping/quote", json=payload)

    assert first.status_code == 200
    assert first.json()["price_cents"] > 0
    assert first.json()["eta_days"] > 0
    assert first.json() == second.json()

    free_payload = {"cep": "01000-000", "items": [{"sku": "P0001-42-PRETO", "qty": 2}]}
    free = await client.post("/shipping/quote", json=free_payload)
    assert free.json()["price_cents"] == 0

    other_region = await client.post(
        "/shipping/quote",
        json={"cep": "90000-000", "items": [{"sku": "P0002-M-BRANCO", "qty": 1}]},
    )
    assert other_region.json()["price_cents"] != first.json()["price_cents"]


@pytest.mark.contract
async def test_shipping_quote_rejects_unknown_sku_and_extra_fields(client: AsyncClient) -> None:
    unknown = await client.post(
        "/shipping/quote",
        json={"cep": "01000-000", "items": [{"sku": "SKU-INEXISTENTE", "qty": 1}]},
    )
    assert unknown.status_code == 422

    extra = await client.post(
        "/shipping/quote",
        json={
            "cep": "01000-000",
            "items": [{"sku": "P0002-M-BRANCO", "qty": 1}],
            "surpresa": True,
        },
    )
    assert extra.status_code == 422


@pytest.mark.contract
async def test_return_eligibility_boundaries_of_seven_days(client: AsyncClient) -> None:
    six_days = await client.get(
        "/returns/eligibility", params={"order_id": "O000001", "sku": "P0001-42-PRETO"}
    )
    assert six_days.status_code == 200
    assert six_days.json()["eligible"] is True
    assert six_days.json()["reason"] == "ok"
    assert six_days.json()["deadline"] is not None

    seven_days = await client.get(
        "/returns/eligibility", params={"order_id": "O000002", "sku": "P0002-M-BRANCO"}
    )
    assert seven_days.json()["eligible"] is True

    eight_days = await client.get(
        "/returns/eligibility", params={"order_id": "O000003", "sku": "P0003-40-AZUL"}
    )
    assert eight_days.json()["eligible"] is False
    assert eight_days.json()["reason"] == "deadline_exceeded"

    not_delivered = await client.get(
        "/returns/eligibility", params={"order_id": "O000007", "sku": "P0001-42-PRETO"}
    )
    assert not_delivered.json()["eligible"] is False
    assert not_delivered.json()["reason"] == "not_delivered"


@pytest.mark.contract
async def test_return_eligibility_uses_mock_today(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_TODAY", "2026-10-30T00:00:00Z")
    http_client = await _make_client(app)
    async with http_client:
        response = await http_client.get(
            "/returns/eligibility", params={"order_id": "O000003", "sku": "P0003-40-AZUL"}
        )
    assert response.json()["eligible"] is True


@pytest.mark.contract
async def test_cancel_order_is_idempotent_and_rejects_non_cancelable(
    client: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "cancel-1"}
    first = await client.post("/orders/O000004/cancel", headers=headers)
    second = await client.post("/orders/O000004/cancel", headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.status_code == 200
    assert second.json() == first.json()

    other_key = await client.post("/orders/O000004/cancel", headers={"Idempotency-Key": "cancel-2"})
    assert other_key.status_code == 409

    shipped = await client.post(
        "/orders/O000007/cancel", headers={"Idempotency-Key": "cancel-shipped"}
    )
    assert shipped.status_code == 409

    no_header = await client.post("/orders/O000005/cancel")
    assert no_header.status_code == 422


@pytest.mark.contract
async def test_create_return_is_idempotent_and_validates_eligibility(
    client: AsyncClient,
) -> None:
    payload = {"order_id": "O000001", "sku": "P0001-42-PRETO", "reason": "tamanho errado"}
    headers = {"Idempotency-Key": "return-1"}

    first = await client.post("/returns", json=payload, headers=headers)
    second = await client.post("/returns", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "return_requested"
    assert second.status_code == 200
    assert second.json() == first.json()

    duplicate = await client.post("/returns", json=payload, headers={"Idempotency-Key": "return-2"})
    assert duplicate.status_code == 409

    expired = await client.post(
        "/returns",
        json={"order_id": "O000003", "sku": "P0003-40-AZUL", "reason": "defeito"},
        headers={"Idempotency-Key": "return-expired"},
    )
    assert expired.status_code == 422

    not_delivered = await client.post(
        "/returns",
        json={"order_id": "O000007", "sku": "P0001-42-PRETO", "reason": "defeito"},
        headers={"Idempotency-Key": "return-not-delivered"},
    )
    assert not_delivered.status_code == 422

    no_header = await client.post("/returns", json=payload)
    assert no_header.status_code == 422


@pytest.mark.contract
async def test_admin_reset_restores_original_state(client: AsyncClient) -> None:
    cancelled = await client.post(
        "/orders/O000004/cancel", headers={"Idempotency-Key": "reset-cancel"}
    )
    assert cancelled.status_code == 200

    reset = await client.post("/_admin/reset")
    assert reset.status_code == 200
    assert reset.json() == {"status": "reset"}

    order = await client.get("/orders/O000004")
    assert order.json()["status"] == "pending_payment"


@pytest.mark.contract
async def test_injected_failure_and_delay_headers(client: AsyncClient) -> None:
    failed = await client.get("/orders/O000001", headers={"X-Mock-Fail": "500"})
    assert failed.status_code == 500

    started = time.perf_counter()
    delayed = await client.get("/orders/O000001", headers={"X-Mock-Delay-Ms": "30"})
    elapsed = time.perf_counter() - started

    assert delayed.status_code == 200
    assert elapsed >= 0.02


@pytest.mark.contract
async def test_env_latency_and_error_rate(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_LATENCY_MS", "30")
    http_client = await _make_client(app)
    async with http_client:
        started = time.perf_counter()
        response = await http_client.get("/products/P0001")
    assert response.status_code == 200
    assert time.perf_counter() - started >= 0.02

    monkeypatch.setenv("MOCK_ERROR_RATE", "1")
    failing_client = await _make_client(app)
    async with failing_client:
        failure = await failing_client.get("/products/P0001")
    assert failure.status_code == 503


@pytest.mark.contract
async def test_mock_seed_makes_error_injection_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_ERROR_RATE", "0.5")
    monkeypatch.setenv("MOCK_SEED", "42")

    async def statuses() -> list[int]:
        http_client = await _make_client(create_app(FIXTURES_DIR))
        async with http_client:
            return [(await http_client.get("/products/P0001")).status_code for _ in range(10)]

    assert await statuses() == await statuses()
