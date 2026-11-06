"""Aplicação FastAPI da loja fake com falhas injetáveis."""

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from mock_store.models import (
    AdminResetResponse,
    AvailabilityResponse,
    CancelResponse,
    Order,
    Product,
    ReturnCreateRequest,
    ReturnCreateResponse,
    ReturnEligibilityResponse,
    ShippingQuoteRequest,
    ShippingQuoteResponse,
)
from mock_store.store import InvalidRequestError, MockStore, NotFoundError

DEFAULT_DATA_DIR = "data/seed"
DEFAULT_TODAY = "2026-11-01T00:00:00Z"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _today() -> datetime:
    raw = os.environ.get("MOCK_TODAY", DEFAULT_TODAY)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.fromisoformat(DEFAULT_TODAY.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _get_store(request: Request) -> MockStore:
    return cast(MockStore, request.app.state.store)


StoreDep = Annotated[MockStore, Depends(_get_store)]


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    data_dir_env = os.environ.get("DATA_DIR", DEFAULT_DATA_DIR)
    resolved = Path(data_dir if data_dir is not None else data_dir_env)
    store = MockStore(resolved)

    app = FastAPI(title="mock_store", version="0.1.0")
    app.state.store = store
    app.state.failure_rng = random.Random(_env_int("MOCK_SEED", 0))

    @app.middleware("http")
    async def inject_failures(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        latency_ms = _env_float("MOCK_LATENCY_MS", 0.0)
        delay_header = request.headers.get("X-Mock-Delay-Ms")
        if delay_header is not None:
            try:
                latency_ms = float(delay_header)
            except ValueError:
                pass
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000)

        fail_header = request.headers.get("X-Mock-Fail")
        if fail_header is not None:
            try:
                status_code = int(fail_header)
            except ValueError:
                status_code = 0
            if 400 <= status_code <= 599:
                return JSONResponse({"detail": "falha injetada"}, status_code=status_code)

        error_rate = _env_float("MOCK_ERROR_RATE", 0.0)
        rng = cast(random.Random, request.app.state.failure_rng)
        if error_rate > 0 and rng.random() < error_rate:
            return JSONResponse({"detail": "falha injetada"}, status_code=503)

        return await call_next(request)

    @app.get("/orders/{order_id}", response_model=Order)
    def get_order(order_id: str, store_dep: StoreDep) -> Order:
        try:
            return store_dep.get_order(order_id)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/customers/{customer_id}/orders", response_model=list[Order])
    def get_customer_orders(customer_id: str, store_dep: StoreDep) -> list[Order]:
        try:
            return store_dep.customer_orders(customer_id)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/products", response_model=list[Product])
    def search_products(
        store_dep: StoreDep,
        query: str = "",
        limit: Annotated[int, Query(ge=1, le=100)] = 5,
    ) -> list[Product]:
        return store_dep.search_products(query, limit)

    @app.get("/products/{product_id}", response_model=Product)
    def get_product(product_id: str, store_dep: StoreDep) -> Product:
        try:
            return store_dep.get_product(product_id)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/products/{product_id}/availability", response_model=AvailabilityResponse)
    def get_availability(
        product_id: str,
        store_dep: StoreDep,
        size: str | None = None,
        color: str | None = None,
    ) -> AvailabilityResponse:
        try:
            return store_dep.availability(product_id, size, color)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/shipping/quote", response_model=ShippingQuoteResponse)
    def shipping_quote(payload: ShippingQuoteRequest, store_dep: StoreDep) -> ShippingQuoteResponse:
        try:
            return store_dep.shipping_quote(payload)
        except InvalidRequestError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/returns/eligibility", response_model=ReturnEligibilityResponse)
    def return_eligibility(
        store_dep: StoreDep,
        order_id: str,
        sku: str,
    ) -> ReturnEligibilityResponse:
        try:
            return store_dep.return_eligibility(order_id, sku, _today())
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/orders/{order_id}/cancel", response_model=CancelResponse)
    def cancel_order(
        order_id: str,
        store_dep: StoreDep,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Response:
        status_code, body = store_dep.cancel(order_id, idempotency_key, _today())
        return JSONResponse(body, status_code=status_code)

    @app.post("/returns", response_model=ReturnCreateResponse)
    def create_return(
        payload: ReturnCreateRequest,
        store_dep: StoreDep,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Response:
        status_code, body = store_dep.create_return(payload, idempotency_key, _today())
        return JSONResponse(body, status_code=status_code)

    @app.post("/_admin/reset", response_model=AdminResetResponse)
    def admin_reset(store_dep: StoreDep) -> AdminResetResponse:
        store_dep.reload()
        return AdminResetResponse(status="reset")

    return app


app = create_app()

__all__ = ["create_app", "app"]
