"""Contrato das ferramentas dos agentes (ADR 0004, 0008, 0010).

Fonte única de verdade para servidores MCP, executor de ferramentas, allowlists e testes de
contrato. Mudar nomes ou campos exige atualizar `data/eval_scenarios` no mesmo PR.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.views import (
    OrderView,
    PolicyChunk,
    ProductView,
    VariantAvailability,
)

OrderId = Annotated[str, Field(pattern=r"^O\d{6}$")]
CustomerId = Annotated[str, Field(pattern=r"^C\d{4}$")]
ProductId = Annotated[str, Field(pattern=r"^P\d{4}$")]
Sku = Annotated[str, Field(min_length=3, max_length=64)]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=128)]


# ---------------------------------------------------------------------------
# Erros tipados
# ---------------------------------------------------------------------------
class ToolErrorCode(StrEnum):
    INVALID_ARGUMENT = "invalid_argument"
    NOT_FOUND = "not_found"
    NOT_CANCELABLE = "not_cancelable"
    NOT_ELIGIBLE = "not_eligible"
    ALREADY_REQUESTED = "already_requested"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_INVALID = "confirmation_invalid"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    NOT_ALLOWED = "not_allowed"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UPSTREAM_ERROR = "upstream_error"


# Erros transitórios: apenas estes podem ser repetidos automaticamente pelo executor.
RETRYABLE_ERRORS: frozenset[ToolErrorCode] = frozenset(
    {ToolErrorCode.UPSTREAM_TIMEOUT, ToolErrorCode.UPSTREAM_UNAVAILABLE}
)


class ToolError(StrictModel):
    """Falha de ferramenta. Nunca carrega stack trace nem detalhe interno da loja."""

    ok: Literal[False] = False
    code: ToolErrorCode
    message: str = Field(max_length=300, description="Texto seguro para o agente ler")
    retryable: bool = False


# ---------------------------------------------------------------------------
# Entradas e saídas (leitura)
# ---------------------------------------------------------------------------
class GetOrderStatusInput(StrictModel):
    order_id: OrderId


class GetOrderStatusOutput(StrictModel):
    ok: Literal[True] = True
    order: OrderView


class ListCustomerOrdersInput(StrictModel):
    customer_id: CustomerId
    limit: Annotated[int, Field(ge=1, le=20)] = 5


class ListCustomerOrdersOutput(StrictModel):
    ok: Literal[True] = True
    orders: tuple[OrderView, ...]


class SearchProductsInput(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=200)]
    limit: Annotated[int, Field(ge=1, le=20)] = 5


class SearchProductsOutput(StrictModel):
    ok: Literal[True] = True
    products: tuple[ProductView, ...]


class CheckAvailabilityInput(StrictModel):
    product_id: ProductId
    size: str | None = None
    color: str | None = None


class CheckAvailabilityOutput(StrictModel):
    ok: Literal[True] = True
    product_id: str
    available: bool
    variants: tuple[VariantAvailability, ...]


class QuoteShippingItem(StrictModel):
    sku: Sku
    qty: Annotated[int, Field(ge=1, le=20)]


class QuoteShippingInput(StrictModel):
    cep: Annotated[str, Field(pattern=r"^\d{5}-?\d{3}$")]
    items: Annotated[tuple[QuoteShippingItem, ...], Field(min_length=1, max_length=20)]


class QuoteShippingOutput(StrictModel):
    ok: Literal[True] = True
    price_cents: Annotated[int, Field(ge=0)]
    eta_days: Annotated[int, Field(ge=0)]
    free_shipping: bool


class CheckReturnEligibilityInput(StrictModel):
    order_id: OrderId
    sku: Sku


class CheckReturnEligibilityOutput(StrictModel):
    ok: Literal[True] = True
    eligible: bool
    reason: Literal[
        "ok", "not_delivered", "deadline_exceeded", "sku_not_in_order", "already_requested"
    ]
    deadline: datetime | None


class SearchPoliciesInput(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=300)]
    top_k: Annotated[int, Field(ge=1, le=8)] = 4


class SearchPoliciesOutput(StrictModel):
    ok: Literal[True] = True
    chunks: tuple[PolicyChunk, ...]


class RequestHandoffInput(StrictModel):
    reason: Annotated[str, Field(min_length=1, max_length=300)]
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    summary: Annotated[str, Field(min_length=1, max_length=2000)]


class RequestHandoffOutput(StrictModel):
    ok: Literal[True] = True
    handoff_id: str


# ---------------------------------------------------------------------------
# Entradas e saídas (irreversíveis, ADR 0008)
# ---------------------------------------------------------------------------
class IrreversibleInput(StrictModel):
    """Base das ferramentas irreversíveis.

    O servidor consome `confirmation_token` (uso único, vinculado a conversa, ação e ao digest
    dos argumentos de ação) ANTES de chamar a loja. Se `idempotency_key` já tem resultado
    registrado com os mesmos argumentos, devolve o resultado guardado sem exigir token novo
    (retry seguro após timeout). Mesma chave com argumentos diferentes: `idempotency_conflict`.
    """

    conversation_id: Annotated[str, Field(min_length=1)]
    confirmation_token: Annotated[str, Field(min_length=1)]
    idempotency_key: IdempotencyKey


class CancelOrderInput(IrreversibleInput):
    order_id: OrderId


class CancelOrderOutput(StrictModel):
    ok: Literal[True] = True
    order_id: str
    status: Literal["cancelled"]
    cancelled_at: datetime


class OpenReturnInput(IrreversibleInput):
    order_id: OrderId
    sku: Sku
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class OpenReturnOutput(StrictModel):
    ok: Literal[True] = True
    order_id: str
    sku: str
    status: Literal["return_requested"]
    requested_at: datetime


# ---------------------------------------------------------------------------
# Registro, allowlists, timeouts
# ---------------------------------------------------------------------------
class ToolSpec(StrictModel):
    name: str
    server: Literal["orders", "catalog", "shipping", "returns", "internal"]
    irreversible: bool
    action_fields: tuple[str, ...] = Field(
        default=(),
        description="Campos do input que entram no digest do token (só irreversíveis)",
    )
    timeout_seconds: float
    max_retries: int = Field(ge=0, le=3)


_READ_TIMEOUT = 3.0
_WRITE_TIMEOUT = 5.0

TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="get_order_status",
            server="orders",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=2,
        ),
        ToolSpec(
            name="list_customer_orders",
            server="orders",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=2,
        ),
        ToolSpec(
            name="cancel_order",
            server="orders",
            irreversible=True,
            action_fields=("order_id",),
            timeout_seconds=_WRITE_TIMEOUT,
            max_retries=1,
        ),
        ToolSpec(
            name="search_products",
            server="catalog",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=2,
        ),
        ToolSpec(
            name="check_availability",
            server="catalog",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=2,
        ),
        ToolSpec(
            name="quote_shipping",
            server="shipping",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=2,
        ),
        ToolSpec(
            name="check_return_eligibility",
            server="returns",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=2,
        ),
        ToolSpec(
            name="open_return",
            server="returns",
            irreversible=True,
            action_fields=("order_id", "sku", "reason"),
            timeout_seconds=_WRITE_TIMEOUT,
            max_retries=1,
        ),
        ToolSpec(
            name="search_policies",
            server="internal",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=1,
        ),
        ToolSpec(
            name="request_handoff",
            server="internal",
            irreversible=False,
            timeout_seconds=_READ_TIMEOUT,
            max_retries=0,
        ),
    )
}

INPUT_MODELS: dict[str, type[StrictModel]] = {
    "get_order_status": GetOrderStatusInput,
    "list_customer_orders": ListCustomerOrdersInput,
    "cancel_order": CancelOrderInput,
    "search_products": SearchProductsInput,
    "check_availability": CheckAvailabilityInput,
    "quote_shipping": QuoteShippingInput,
    "check_return_eligibility": CheckReturnEligibilityInput,
    "open_return": OpenReturnInput,
    "search_policies": SearchPoliciesInput,
    "request_handoff": RequestHandoffInput,
}

OUTPUT_MODELS: dict[str, type[StrictModel]] = {
    "get_order_status": GetOrderStatusOutput,
    "list_customer_orders": ListCustomerOrdersOutput,
    "cancel_order": CancelOrderOutput,
    "search_products": SearchProductsOutput,
    "check_availability": CheckAvailabilityOutput,
    "quote_shipping": QuoteShippingOutput,
    "check_return_eligibility": CheckReturnEligibilityOutput,
    "open_return": OpenReturnOutput,
    "search_policies": SearchPoliciesOutput,
    "request_handoff": RequestHandoffOutput,
}

# Allowlist aplicada no executor, fora do LLM (ADR 0010).
AGENT_ALLOWLIST: dict[str, frozenset[str]] = {
    "Pedidos": frozenset(
        {"get_order_status", "list_customer_orders", "cancel_order", "request_handoff"}
    ),
    "CatalogoVendas": frozenset(
        {"search_products", "check_availability", "quote_shipping", "request_handoff"}
    ),
    "Politicas": frozenset({"search_policies", "check_return_eligibility", "request_handoff"}),
    "PosVenda": frozenset(
        {
            "get_order_status",
            "check_return_eligibility",
            "open_return",
            "search_policies",
            "request_handoff",
        }
    ),
}
