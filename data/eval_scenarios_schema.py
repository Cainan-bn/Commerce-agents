"""Schema Pydantic v2 estrito dos cenários de avaliação (data/README.md)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SPLITS: tuple[str, ...] = ("dev", "holdout")

CATEGORIES: tuple[str, ...] = (
    "pedidos",
    "catalogo",
    "politicas",
    "pos_venda",
    "injection",
    "ambiguo",
    "handoff",
)

TOOLS: tuple[str, ...] = (
    "get_order_status",
    "list_customer_orders",
    "cancel_order",
    "search_products",
    "check_availability",
    "quote_shipping",
    "check_return_eligibility",
    "open_return",
    "search_policies",
    "request_handoff",
)

IRREVERSIBLE_TOOLS: frozenset[str] = frozenset({"cancel_order", "open_return"})

Split = Literal["dev", "holdout"]
Category = Literal[
    "pedidos",
    "catalogo",
    "politicas",
    "pos_venda",
    "injection",
    "ambiguo",
    "handoff",
]
Outcome = Literal["resolved", "handoff", "refused", "clarified"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ToolCall(StrictModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Expected(StrictModel):
    intent: str
    agent: str
    tools: list[ToolCall] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    irreversible_without_confirmation: bool
    must_mention: list[str] = Field(default_factory=list)
    outcome: Outcome
    citations_required: bool = False
    leaks: Literal["forbidden"] | None = None


class EvalScenario(StrictModel):
    id: str
    split: Split
    category: Category
    persona: str
    goal: str
    fixtures: dict[str, str] = Field(default_factory=dict)
    turns: list[str]
    expected: Expected
    notes: str | None = None
