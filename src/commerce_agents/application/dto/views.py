"""DTOs de leitura retornados pelos ports."""

from datetime import datetime

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel


class OrderItemView(StrictModel):
    """Item do pedido como o agente vê: só o SKU e a quantidade (sem preço)."""

    sku: str
    qty: int = Field(ge=1)


class OrderView(StrictModel):
    order_id: str
    customer_id: str
    status: str
    tracking_code: str | None
    created_at: datetime
    delivered_at: datetime | None
    total_cents: int = Field(ge=0)
    items: tuple[OrderItemView, ...] = ()


class VariantAvailability(StrictModel):
    sku: str
    size: str
    color: str
    stock: int = Field(ge=0)


class ProductView(StrictModel):
    product_id: str
    name: str
    brand: str
    price_cents: int = Field(ge=0)
    variants: tuple[VariantAvailability, ...]


class PolicyChunk(StrictModel):
    """Trecho de política recuperado, sempre com fonte para citação."""

    chunk_id: str
    document: str
    section: str
    text: str
    score: float
    corpus_version: str


class LLMMessage(StrictModel):
    role: str
    content: str


class LLMResult(StrictModel):
    content: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    # Elo que respondeu (ADR 0017): preenchido pelo breaker/fallback; `None` sem resiliência.
    provider: str | None = None


class IntentDecision(StrictModel):
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
