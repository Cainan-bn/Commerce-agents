"""DTOs de leitura retornados pelos ports."""

from datetime import datetime

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel


class OrderView(StrictModel):
    order_id: str
    customer_id: str
    status: str
    tracking_code: str | None
    created_at: datetime
    delivered_at: datetime | None
    total_cents: int = Field(ge=0)


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


class IntentDecision(StrictModel):
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
