"""Executor de ferramentas: allowlist, validação, token, idempotência, retry e auditoria.

Aplica as regras do ADR 0008/0010/0011 fora do LLM e nunca lança para o chamador: toda falha
vira `ToolError` com mensagem segura (sem corpo da loja, URL ou stack).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.events import ToolInvoked
from commerce_agents.application.dto.tools import (
    AGENT_ALLOWLIST,
    INPUT_MODELS,
    OUTPUT_MODELS,
    RETRYABLE_ERRORS,
    TOOL_SPECS,
    CancelOrderOutput,
    CheckAvailabilityInput,
    CheckAvailabilityOutput,
    CheckReturnEligibilityInput,
    CheckReturnEligibilityOutput,
    GetOrderStatusInput,
    GetOrderStatusOutput,
    ListCustomerOrdersInput,
    ListCustomerOrdersOutput,
    OpenReturnInput,
    OpenReturnOutput,
    QuoteShippingInput,
    QuoteShippingOutput,
    SearchProductsInput,
    SearchProductsOutput,
    ToolError,
    ToolErrorCode,
    ToolSpec,
    action_digest,
)
from commerce_agents.application.dto.views import OrderView, ProductView, VariantAvailability
from commerce_agents.application.ports.confirmation import (
    ConfirmationTokenStore,
    IdempotencyRegistry,
)

logger = logging.getLogger(__name__)

ToolResult = StrictModel | ToolError
InternalHandler = Callable[[str, Any], Awaitable[ToolResult]]
AuditSink = Callable[[ToolInvoked], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]

_BACKOFF_BASE_SECONDS = 0.2
_FREE_TEXT_AUDIT_LIMIT = 80
_ELIGIBILITY_REASONS = frozenset(
    {"not_delivered", "deadline_exceeded", "sku_not_in_order", "already_requested"}
)
_REUSED_KEY_PREFIX = "idempotency key reutilizada"
_PENDING = "__pending__"

_MESSAGES: dict[ToolErrorCode, str] = {
    ToolErrorCode.INVALID_ARGUMENT: "Os argumentos da ferramenta são inválidos.",
    ToolErrorCode.NOT_FOUND: "Recurso não encontrado.",
    ToolErrorCode.NOT_CANCELABLE: "O pedido não pode mais ser cancelado.",
    ToolErrorCode.NOT_ELIGIBLE: "O item não é elegível para devolução.",
    ToolErrorCode.ALREADY_REQUESTED: "Já existe uma solicitação de devolução para este item.",
    ToolErrorCode.CONFIRMATION_REQUIRED: "Esta ação exige confirmação explícita do cliente.",
    ToolErrorCode.CONFIRMATION_INVALID: "A confirmação é inválida, expirada ou já foi usada.",
    ToolErrorCode.IDEMPOTENCY_CONFLICT: (
        "A chave de idempotência já foi usada com argumentos diferentes."
    ),
    ToolErrorCode.NOT_ALLOWED: "Este agente não pode usar esta ferramenta.",
    ToolErrorCode.UPSTREAM_TIMEOUT: "A loja demorou demais para responder.",
    ToolErrorCode.UPSTREAM_UNAVAILABLE: "A loja está temporariamente indisponível.",
    ToolErrorCode.UPSTREAM_ERROR: "A loja retornou um erro inesperado.",
}


def _error(code: ToolErrorCode, message: str | None = None) -> ToolError:
    return ToolError(
        code=code,
        message=message or _MESSAGES[code],
        retryable=code in RETRYABLE_ERRORS,
    )


def _lax[M: StrictModel](model: type[M], data: Mapping[str, Any]) -> M:
    """Valida dados vindos de JSON da loja (datas como texto, listas como tuplas)."""
    return model.model_validate(data, strict=False)


# ---------------------------------------------------------------------------
# Rotas da loja: construção da requisição e conversão explícita da resposta
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None


def _order_view(body: Mapping[str, Any]) -> OrderView:
    return _lax(
        OrderView,
        {
            "order_id": body["order_id"],
            "customer_id": body["customer_id"],
            "status": body["status"],
            "tracking_code": body.get("tracking_code"),
            "created_at": body["created_at"],
            "delivered_at": body.get("delivered_at"),
            "total_cents": body["total_cents"],
        },
    )


def _variants(raw: list[Mapping[str, Any]]) -> tuple[VariantAvailability, ...]:
    return tuple(
        _lax(
            VariantAvailability,
            {k: item[k] for k in ("sku", "size", "color", "stock")},
        )
        for item in raw
    )


def _product_view(body: Mapping[str, Any]) -> ProductView:
    return ProductView(
        product_id=body["product_id"],
        name=body["name"],
        brand=body["brand"],
        price_cents=body["price_cents"],
        variants=_variants(body["variants"]),
    )


def _get_order_request(args: GetOrderStatusInput) -> _Request:
    return _Request("GET", f"/orders/{args.order_id}")


def _get_order_parse(args: GetOrderStatusInput, body: Any) -> StrictModel:
    return GetOrderStatusOutput(order=_order_view(body))


def _list_orders_request(args: ListCustomerOrdersInput) -> _Request:
    return _Request("GET", f"/customers/{args.customer_id}/orders")


def _list_orders_parse(args: ListCustomerOrdersInput, body: Any) -> StrictModel:
    return ListCustomerOrdersOutput(orders=tuple(_order_view(o) for o in body[: args.limit]))


def _search_products_request(args: SearchProductsInput) -> _Request:
    return _Request("GET", "/products", params={"query": args.query, "limit": args.limit})


def _search_products_parse(args: SearchProductsInput, body: Any) -> StrictModel:
    return SearchProductsOutput(products=tuple(_product_view(p) for p in body))


def _availability_request(args: CheckAvailabilityInput) -> _Request:
    params = {k: v for k, v in (("size", args.size), ("color", args.color)) if v is not None}
    return _Request("GET", f"/products/{args.product_id}/availability", params=params)


def _availability_parse(args: CheckAvailabilityInput, body: Any) -> StrictModel:
    return CheckAvailabilityOutput(
        product_id=body["product_id"],
        available=body["available"],
        variants=_variants(body["variants"]),
    )


def _quote_request(args: QuoteShippingInput) -> _Request:
    return _Request(
        "POST",
        "/shipping/quote",
        json={
            "cep": args.cep,
            "items": [{"sku": item.sku, "qty": item.qty} for item in args.items],
        },
    )


def _quote_parse(args: QuoteShippingInput, body: Any) -> StrictModel:
    return QuoteShippingOutput(
        price_cents=body["price_cents"],
        eta_days=body["eta_days"],
        free_shipping=body["price_cents"] == 0,
    )


def _eligibility_request(args: CheckReturnEligibilityInput) -> _Request:
    return _Request(
        "GET", "/returns/eligibility", params={"order_id": args.order_id, "sku": args.sku}
    )


def _eligibility_parse(args: CheckReturnEligibilityInput, body: Any) -> StrictModel:
    return _lax(
        CheckReturnEligibilityOutput,
        {"eligible": body["eligible"], "reason": body["reason"], "deadline": body["deadline"]},
    )


def _cancel_request(args: Any) -> _Request:
    return _Request("POST", f"/orders/{args.order_id}/cancel")


def _cancel_parse(args: Any, body: Any) -> StrictModel:
    return _lax(
        CancelOrderOutput,
        {k: body[k] for k in ("order_id", "status", "cancelled_at")},
    )


def _open_return_request(args: OpenReturnInput) -> _Request:
    return _Request(
        "POST",
        "/returns",
        json={"order_id": args.order_id, "sku": args.sku, "reason": args.reason},
    )


def _open_return_parse(args: OpenReturnInput, body: Any) -> StrictModel:
    return _lax(
        OpenReturnOutput,
        {k: body[k] for k in ("order_id", "sku", "status", "requested_at")},
    )


_ROUTES: dict[str, tuple[Callable[[Any], _Request], Callable[[Any, Any], StrictModel]]] = {
    "get_order_status": (_get_order_request, _get_order_parse),
    "list_customer_orders": (_list_orders_request, _list_orders_parse),
    "search_products": (_search_products_request, _search_products_parse),
    "check_availability": (_availability_request, _availability_parse),
    "quote_shipping": (_quote_request, _quote_parse),
    "check_return_eligibility": (_eligibility_request, _eligibility_parse),
    "cancel_order": (_cancel_request, _cancel_parse),
    "open_return": (_open_return_request, _open_return_parse),
}


def _http_error(tool_name: str, response: httpx.Response) -> ToolError:
    """Traduz o status da loja (docs/architecture/tools.md) sem expor o corpo."""
    status = response.status_code
    if status == 404:
        return _error(ToolErrorCode.NOT_FOUND)
    if status == 409 and tool_name == "cancel_order":
        return _error(ToolErrorCode.NOT_CANCELABLE)
    if status == 409 and tool_name == "open_return":
        return _error(ToolErrorCode.ALREADY_REQUESTED)
    if status == 422:
        detail = _detail(response)
        if detail.startswith(_REUSED_KEY_PREFIX):
            return _error(ToolErrorCode.IDEMPOTENCY_CONFLICT)
        if tool_name == "open_return" and detail in _ELIGIBILITY_REASONS:
            return _error(ToolErrorCode.NOT_ELIGIBLE)
        return _error(ToolErrorCode.INVALID_ARGUMENT)
    if status in (502, 503, 504):
        return _error(ToolErrorCode.UPSTREAM_UNAVAILABLE)
    return _error(ToolErrorCode.UPSTREAM_ERROR)


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return detail if isinstance(detail, str) else ""


def _audit_arguments(arguments: Mapping[str, Any]) -> dict[str, str | int | float | bool | None]:
    """Argumentos auditáveis: sem token, com texto livre truncado e valores compostos em JSON."""
    audited: dict[str, str | int | float | bool | None] = {}
    for name, value in arguments.items():
        if name == "confirmation_token":
            continue
        if isinstance(value, bool | int | float) or value is None:
            audited[name] = value
        elif isinstance(value, str):
            limit = _FREE_TEXT_AUDIT_LIMIT if name in ("reason", "summary") else 200
            audited[name] = value[:limit]
        else:
            audited[name] = json.dumps(value, ensure_ascii=False, default=str)[:200]
    return audited


class ToolExecutor:
    """Ponto único de execução de ferramentas dos agentes."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        tokens: ConfirmationTokenStore,
        idempotency: IdempotencyRegistry,
        sleep: Sleep = asyncio.sleep,
        audit: AuditSink | None = None,
        internal_handlers: Mapping[str, InternalHandler] | None = None,
    ) -> None:
        self._client = client
        self._tokens = tokens
        self._idempotency = idempotency
        self._sleep = sleep
        self._audit = audit
        self._internal_handlers = dict(internal_handlers or {})

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> ToolResult:
        started = time.monotonic()
        spec = TOOL_SPECS.get(tool_name)
        try:
            result = await self._run(agent, tool_name, spec, arguments, conversation_id)
        except Exception:
            logger.exception("falha inesperada ao executar a ferramenta %s", tool_name)
            result = _error(ToolErrorCode.UPSTREAM_ERROR)
        await self._record(agent, tool_name, spec, arguments, conversation_id, result, started)
        return result

    async def _run(
        self,
        agent: str,
        tool_name: str,
        spec: ToolSpec | None,
        arguments: Mapping[str, Any],
        conversation_id: str | None,
    ) -> ToolResult:
        if spec is None or tool_name not in AGENT_ALLOWLIST.get(agent, frozenset()):
            return _error(ToolErrorCode.NOT_ALLOWED)
        effective = dict(arguments)
        if spec.irreversible:
            if conversation_id and not effective.get("conversation_id"):
                effective["conversation_id"] = conversation_id
            if not all(
                effective.get(name)
                for name in ("confirmation_token", "idempotency_key", "conversation_id")
            ):
                return _error(ToolErrorCode.CONFIRMATION_REQUIRED)
        try:
            validated = INPUT_MODELS[tool_name].model_validate(effective, strict=False)
        except ValidationError as error:
            fields = sorted({".".join(str(p) for p in e["loc"]) for e in error.errors()})
            names = ", ".join(name for name in fields if name)
            message = f"{_MESSAGES[ToolErrorCode.INVALID_ARGUMENT]} Campos: {names}."
            return _error(ToolErrorCode.INVALID_ARGUMENT, message[:300])
        if spec.server == "internal":
            return await self._run_internal(agent, tool_name, validated)
        if spec.irreversible:
            return await self._run_irreversible(tool_name, spec, validated)
        return await self._call_store(tool_name, spec, validated, idempotency_key=None)

    async def _run_internal(self, agent: str, tool_name: str, validated: StrictModel) -> ToolResult:
        handler = self._internal_handlers.get(tool_name)
        if handler is None:
            return _error(ToolErrorCode.NOT_FOUND)
        return await handler(agent, validated)

    async def _run_irreversible(
        self, tool_name: str, spec: ToolSpec, validated: StrictModel
    ) -> ToolResult:
        data = validated.model_dump()
        key: str = data["idempotency_key"]
        digest = action_digest(tool_name, data)
        stored = await self._idempotency.get(key)
        if stored is not None and stored[0] != digest:
            return _error(ToolErrorCode.IDEMPOTENCY_CONFLICT)
        if stored is not None and stored[1] != _PENDING:
            return self._decode(tool_name, stored[1])
        if stored is None:
            consumed = await self._tokens.consume(
                data["confirmation_token"], data["conversation_id"], tool_name, digest
            )
            if not consumed:
                return _error(ToolErrorCode.CONFIRMATION_INVALID)
            await self._idempotency.put(key, digest, _PENDING)
        # PENDENTE: token já consumido; reenvia à loja com a mesma chave (idempotente).
        result = await self._call_store(tool_name, spec, validated, idempotency_key=key)
        if not (isinstance(result, ToolError) and result.retryable):
            await self._idempotency.put(key, digest, result.model_dump_json())
        return result

    @staticmethod
    def _decode(tool_name: str, result_json: str) -> ToolResult:
        if json.loads(result_json).get("ok") is False:
            return ToolError.model_validate_json(result_json)
        return OUTPUT_MODELS[tool_name].model_validate_json(result_json)

    async def _call_store(
        self,
        tool_name: str,
        spec: ToolSpec,
        validated: StrictModel,
        *,
        idempotency_key: str | None,
    ) -> ToolResult:
        build, parse = _ROUTES[tool_name]
        request = build(validated)
        attempt = 0
        while True:
            result = await self._attempt(
                tool_name, spec, request, validated, parse, idempotency_key
            )
            if (
                isinstance(result, ToolError)
                and result.code in RETRYABLE_ERRORS
                and attempt < spec.max_retries
            ):
                await self._sleep(_BACKOFF_BASE_SECONDS * 2**attempt)
                attempt += 1
                continue
            return result

    async def _attempt(
        self,
        tool_name: str,
        spec: ToolSpec,
        request: _Request,
        validated: StrictModel,
        parse: Callable[[Any, Any], StrictModel],
        idempotency_key: str | None,
    ) -> ToolResult:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        try:
            async with asyncio.timeout(spec.timeout_seconds):
                response = await self._client.request(
                    request.method,
                    request.path,
                    params=request.params,
                    json=request.json,
                    headers=headers,
                    timeout=spec.timeout_seconds,
                )
        except (TimeoutError, httpx.TimeoutException):
            return _error(ToolErrorCode.UPSTREAM_TIMEOUT)
        except httpx.TransportError:
            return _error(ToolErrorCode.UPSTREAM_UNAVAILABLE)
        if response.status_code != 200:
            return _http_error(tool_name, response)
        try:
            return parse(validated, response.json())
        except (ValueError, KeyError, TypeError):
            return _error(ToolErrorCode.UPSTREAM_ERROR)

    async def _record(
        self,
        agent: str,
        tool_name: str,
        spec: ToolSpec | None,
        arguments: Mapping[str, Any],
        conversation_id: str | None,
        result: ToolResult,
        started: float,
    ) -> None:
        if self._audit is None:
            return
        from_arguments = arguments.get("conversation_id")
        event = ToolInvoked(
            conversation_id=(
                from_arguments
                if isinstance(from_arguments, str) and from_arguments
                else conversation_id or "unknown"
            ),
            agent=agent,
            tool_name=tool_name,
            arguments=_audit_arguments(arguments),
            irreversible=spec.irreversible if spec else False,
            succeeded=not isinstance(result, ToolError),
            latency_ms=int((time.monotonic() - started) * 1000),
            invoked_at=datetime.now(UTC),
        )
        try:
            await self._audit(event)
        except Exception:
            logger.exception("falha ao registrar auditoria da ferramenta %s", tool_name)
