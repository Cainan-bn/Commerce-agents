"""Mapas e limites fixos do turno (ADR 0013). Decisões de roteamento vivem em código."""

from commerce_agents.application.dto.agents import Intent

AGENT_FOR_INTENT: dict[Intent, str] = {
    Intent.ORDER_STATUS: "pedidos",
    Intent.LIST_ORDERS: "pedidos",
    Intent.CANCEL_ORDER: "pedidos",
    Intent.PRODUCT_SEARCH: "catalogo",
    Intent.AVAILABILITY: "catalogo",
    Intent.SHIPPING_QUOTE: "catalogo",
    Intent.POLICY_QUESTION: "politicas",
    Intent.RETURN_ELIGIBILITY: "pos_venda",
    Intent.RETURN_REQUEST: "pos_venda",
    Intent.HANDOFF_REQUEST: "humano",
    Intent.AMBIGUOUS: "geral",
    Intent.INJECTION_GUARD: "geral",
}

# Chave do agente no estado -> chave da allowlist em `AGENT_ALLOWLIST`.
AGENT_TOOL_KEY: dict[str, str] = {
    "pedidos": "Pedidos",
    "catalogo": "CatalogoVendas",
    "politicas": "Politicas",
    "pos_venda": "PosVenda",
}

MAX_TOOL_STEPS = 4
MIN_CONFIDENCE = 0.5
