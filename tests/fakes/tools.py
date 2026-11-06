"""Casos de ferramenta com dados reais de data/seed e helpers de token e executor."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

from commerce_agents.application.dto.tools import action_digest
from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "data" / "seed"
STORE_URL = "http://store"
MOCK_TODAY = "2026-11-01T00:00:00Z"
CONVERSATION_ID = "conv-test-1"
TOKEN_TTL_SECONDS = 300

READ_TOOLS: tuple[str, ...] = (
    "get_order_status",
    "list_customer_orders",
    "search_products",
    "check_availability",
    "quote_shipping",
    "check_return_eligibility",
)
IRREVERSIBLE_TOOLS: tuple[str, ...] = ("cancel_order", "open_return")

AGENT_FOR_TOOL: dict[str, str] = {
    "get_order_status": "Pedidos",
    "list_customer_orders": "Pedidos",
    "search_products": "CatalogoVendas",
    "check_availability": "CatalogoVendas",
    "quote_shipping": "CatalogoVendas",
    "check_return_eligibility": "PosVenda",
    "cancel_order": "Pedidos",
    "open_return": "PosVenda",
    "search_policies": "Politicas",
    "request_handoff": "Pedidos",
}

# Argumentos válidos contra o seed real: pedidos O000001 (entregue, no prazo), O000004
# (entregue, prazo vencido), O000014 (paid, cancelável), O000015 (processing, cancelável),
# O000026 (cancelled, não cancelável), O000049 (return_requested).
SAMPLE_ARGUMENTS: dict[str, dict[str, Any]] = {
    "get_order_status": {"order_id": "O000001"},
    "list_customer_orders": {"customer_id": "C0053"},
    "search_products": {"query": "tênis"},
    "check_availability": {"product_id": "P0001"},
    "quote_shipping": {"cep": "76169-162", "items": [{"sku": "P0168-GG-AZUL", "qty": 1}]},
    "check_return_eligibility": {"order_id": "O000001", "sku": "P0168-GG-AZUL"},
    "cancel_order": {
        "conversation_id": CONVERSATION_ID,
        "confirmation_token": "token-de-exemplo",
        "idempotency_key": "idem-cancel-exemplo",
        "order_id": "O000014",
    },
    "open_return": {
        "conversation_id": CONVERSATION_ID,
        "confirmation_token": "token-de-exemplo",
        "idempotency_key": "idem-return-exemplo",
        "order_id": "O000001",
        "sku": "P0168-GG-AZUL",
        "reason": "tamanho errado",
    },
    "search_policies": {"query": "prazo de devolução"},
    "request_handoff": {"reason": "cliente pediu atendente", "summary": "resumo da conversa"},
}


def read_seed(name: str) -> list[dict[str, Any]]:
    """Lê um jsonl de data/seed sem usar o mock_store."""
    with (SEED_DIR / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def irreversible_arguments(
    tool_name: str, token: str, idempotency_key: str, **action_fields: str
) -> dict[str, Any]:
    """Monta os argumentos de uma ferramenta irreversível com token e chave informados."""
    assert tool_name in IRREVERSIBLE_TOOLS
    return {
        "conversation_id": CONVERSATION_ID,
        "confirmation_token": token,
        "idempotency_key": idempotency_key,
        **action_fields,
    }


async def issue_token(
    tokens: InMemoryTokenStore,
    tool_name: str,
    arguments: Mapping[str, object],
    *,
    conversation_id: str = CONVERSATION_ID,
) -> str:
    """Emite token da mesma forma que o caso de uso de confirmação (ADR 0008)."""
    digest = action_digest(tool_name, arguments)
    return await tokens.issue(conversation_id, tool_name, digest, TOKEN_TTL_SECONDS)


def build_executor(
    *,
    client: httpx.AsyncClient,
    tokens: InMemoryTokenStore,
    idempotency: InMemoryIdempotencyRegistry,
    sleep: Callable[[float], Awaitable[None]],
    **options: Any,
) -> Any:
    """Instancia o ToolExecutor sob teste.

    O import é feito aqui, e não no topo dos módulos de teste, para que a coleta funcione
    mesmo antes de o módulo existir; sem ele, cada teste falha com ModuleNotFoundError.
    """
    from commerce_agents.infrastructure.mcp.executor import ToolExecutor

    return ToolExecutor(
        client=client,
        tokens=tokens,
        idempotency=idempotency,
        sleep=sleep,
        **options,
    )
