"""Fakes do grafo de atendimento: roteador, loja (ToolInvoker), memória e helpers de turno."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from commerce_agents.application.dto.tools import (
    CancelOrderOutput,
    GetOrderStatusOutput,
    ListCustomerOrdersOutput,
    SearchPoliciesOutput,
    ToolError,
    ToolErrorCode,
)
from commerce_agents.application.dto.views import IntentDecision, OrderView, PolicyChunk
from tests.fakes.clock import BASE_TIME


class FakeRouter:
    """IntentRouter fake: devolve sempre a mesma decisão e registra os textos recebidos."""

    def __init__(self, intent: str, confidence: float = 0.9) -> None:
        self.intent = intent
        self.confidence = confidence
        self.calls: list[str] = []

    async def route(self, text: str) -> IntentDecision:
        self.calls.append(text)
        return IntentDecision(intent=self.intent, confidence=self.confidence)


class FakeMemory:
    """CustomerMemory fake: sem preferências, registra escritas."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str, str]] = []

    async def get_preferences(self, customer_id: str) -> dict[str, str]:
        return {}

    async def set_preference(self, customer_id: str, key: str, value: str) -> None:
        self.writes.append((customer_id, key, value))


class StoreStub:
    """ToolInvoker fake da loja: pedidos com dono, estado de cancelamento e chunks de política."""

    def __init__(
        self,
        owners: Mapping[str, str],
        *,
        search_chunks: tuple[PolicyChunk, ...] = (),
        tool_results: Mapping[str, Callable[[dict[str, Any]], object]] | None = None,
    ) -> None:
        self.owners = dict(owners)
        self.status = {order_id: "paid" for order_id in owners}
        self.search_chunks = search_chunks
        self.tool_results = dict(tool_results or {})
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> Any:
        args = dict(arguments)
        self.calls.append((agent, tool_name, args))
        if tool_name in self.tool_results:
            return self.tool_results[tool_name](args)
        if tool_name == "get_order_status":
            order_id = args["order_id"]
            if order_id not in self.owners:
                return ToolError(code=ToolErrorCode.NOT_FOUND, message="pedido não encontrado")
            order = OrderView(
                order_id=order_id,
                customer_id=self.owners[order_id],
                status=self.status[order_id],
                tracking_code="TH100000001BR",
                created_at=BASE_TIME,
                delivered_at=None,
                total_cents=1000,
            )
            return GetOrderStatusOutput(order=order)
        if tool_name == "cancel_order":
            order_id = args["order_id"]
            self.status[order_id] = "cancelled"
            return CancelOrderOutput(order_id=order_id, status="cancelled", cancelled_at=BASE_TIME)
        if tool_name == "list_customer_orders":
            return ListCustomerOrdersOutput(orders=())
        if tool_name == "search_policies":
            return SearchPoliciesOutput(chunks=self.search_chunks)
        return ToolError(code=ToolErrorCode.NOT_FOUND, message="ferramenta não tratada no fake")

    def real_calls(self, tool_name: str) -> list[dict[str, Any]]:
        return [args for _, name, args in self.calls if name == tool_name]


def policy_chunk(chunk_id: str, text: str = "Trecho de política.") -> PolicyChunk:
    document, _, _ = chunk_id.partition("#")
    return PolicyChunk(
        chunk_id=chunk_id,
        document=document,
        section="Seção",
        text=text,
        score=1.0,
        corpus_version="corpus-de-teste",
    )


def turn_input(
    conversation_id: str,
    customer_id: str,
    text: str,
    *,
    message_id: str | None = None,
    budget: int = 20,
) -> dict[str, Any]:
    """Estado de entrada de um turno (ingest anexa a mensagem do cliente como dado)."""
    return {
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "channel": "web",
        "messages": [{"role": "user", "content": text}],
        "token_budget_remaining": budget,
        "message_id": message_id or f"m-{conversation_id}-{text[:8]}",
    }


def key_factory() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"idem-graph-{next(counter):06d}"


def fixed_time() -> datetime:
    return BASE_TIME
