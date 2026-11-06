"""Estado do grafo LangGraph. Contrato fixo; mudanças exigem ADR (0003, 0013)."""

from typing import Any, Literal, TypedDict

ActiveAgent = Literal["pedidos", "catalogo", "politicas", "pos_venda", "humano", "geral"]


class AgentState(TypedDict, total=False):
    conversation_id: str
    customer_id: str  # vem do canal autenticado; NUNCA de argumento do LLM
    channel: str
    messages: list[dict[str, str]]  # role/content; conteúdo do cliente sempre tratado como dado
    intent: str
    intent_confidence: float
    active_agent: ActiveAgent
    # `PendingAction` (application/dto/confirmation.py) serializado com model_dump(mode="json")
    pending_action: dict[str, Any] | None
    policy_citations: list[str]
    handoff_reason: str | None
    token_budget_remaining: int
    reply: str  # resposta do turno corrente ao cliente
    injection_flagged: bool
