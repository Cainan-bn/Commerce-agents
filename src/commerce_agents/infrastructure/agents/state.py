"""Estado do grafo LangGraph. Contrato fixo; mudanças exigem ADR (0003)."""

from typing import Literal, TypedDict


class PendingAction(TypedDict):
    """Ação irreversível proposta, aguardando confirmação do cliente."""

    action: str
    arguments: dict[str, str]
    idempotency_key: str
    confirmation_token: str


class AgentState(TypedDict, total=False):
    conversation_id: str
    customer_id: str
    channel: str
    messages: list[dict[str, str]]  # role/content; conteúdo do cliente sempre tratado como dado
    intent: str
    intent_confidence: float
    active_agent: Literal["pedidos", "catalogo_vendas", "politicas", "pos_venda", "handoff"]
    pending_action: PendingAction | None
    policy_citations: list[str]
    handoff_reason: str | None
    token_budget_remaining: int
