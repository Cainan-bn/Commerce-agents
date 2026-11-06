"""Serviço de conversa: um turno do grafo por mensagem recebida (ADR 0013)."""

from collections.abc import Callable
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from commerce_agents.application.dto.agents import OutboundReply
from commerce_agents.application.dto.events import InboundMessageReceived

DEFAULT_TOKEN_BUDGET = 20_000


class ConversationService:
    """Executa o turno no grafo, com `thread_id` = `conversation_id`."""

    def __init__(
        self,
        graph_factory: Callable[[], CompiledStateGraph[Any, Any, Any, Any]],
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        self._graph_factory = graph_factory
        self._token_budget = token_budget

    async def handle(self, event: InboundMessageReceived, customer_id: str) -> OutboundReply:
        graph = self._graph_factory()
        config: Any = {"configurable": {"thread_id": event.conversation_id}}
        previous = (await graph.aget_state(config)).values
        budget = previous.get("token_budget_remaining", self._token_budget)
        state = await graph.ainvoke(
            {
                "conversation_id": event.conversation_id,
                "message_id": event.message_id,
                "customer_id": customer_id,
                "channel": event.channel.value,
                "messages": [{"role": "user", "content": event.text}],
                "token_budget_remaining": budget,
            },
            config=config,
        )
        return OutboundReply(
            conversation_id=event.conversation_id,
            text=state["reply"],
            citations=tuple(state.get("policy_citations", [])),
            agent=state["active_agent"],
            handoff=state.get("handoff_reason") is not None and state["active_agent"] == "humano",
            awaiting_confirmation=state.get("pending_action") is not None,
        )
