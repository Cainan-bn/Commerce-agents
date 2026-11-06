"""Contrato dos agentes: intenções, ações do LLM e resposta ao canal (ADR 0013)."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel


class Intent(StrEnum):
    """Vocabulário dos cenários de avaliação (`data/eval_scenarios`)."""

    ORDER_STATUS = "order_status"
    LIST_ORDERS = "list_orders"
    CANCEL_ORDER = "cancel_order"
    PRODUCT_SEARCH = "product_search"
    AVAILABILITY = "availability"
    SHIPPING_QUOTE = "shipping_quote"
    POLICY_QUESTION = "policy_question"
    RETURN_ELIGIBILITY = "return_eligibility"
    RETURN_REQUEST = "return_request"
    HANDOFF_REQUEST = "handoff_request"
    AMBIGUOUS = "ambiguous"
    INJECTION_GUARD = "injection_guard"


class ToolCall(StrictModel):
    """O LLM pede uma ferramenta. `arguments` é validado pelo ToolExecutor, não pelo grafo."""

    type: Literal["tool_call"] = "tool_call"
    tool: Annotated[str, Field(min_length=1, max_length=64)]
    arguments: dict[str, Any] = Field(default_factory=dict)


class FinalAnswer(StrictModel):
    """O LLM encerra o turno com texto ao cliente e as fontes que usou."""

    type: Literal["final"] = "final"
    text: Annotated[str, Field(min_length=1, max_length=1500)]
    citations: tuple[str, ...] = Field(
        default=(), description="chunk_id de trechos de política recuperados neste turno"
    )


class OutboundReply(StrictModel):
    """Resposta do orquestrador para o canal (Fase 07)."""

    conversation_id: str
    text: str
    citations: tuple[str, ...] = ()
    agent: str
    handoff: bool = False
    awaiting_confirmation: bool = False
