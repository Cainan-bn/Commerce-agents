"""Grafo de atendimento montado com fakes, para testes que olham o que ele emite."""

from __future__ import annotations

import json
from typing import Any

from commerce_agents.application.dto.views import LLMMessage, LLMResult
from tests.fakes.agents import FakeMemory, FakeRouter, key_factory, turn_input
from tests.fakes.clock import FakeClock
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.scripted_llm import ScriptedLLM

CUSTOMER = "C0001"


def tool_call(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"type": "tool_call", "tool": name, "arguments": arguments})


def final(text: str, citations: list[str] | None = None) -> str:
    return json.dumps({"type": "final", "text": text, "citations": citations or []})


class ProviderLLM(ScriptedLLM):
    """`ScriptedLLM` cujo `LLMResult` informa o provider que respondeu (ADR 0017)."""

    def __init__(self, provider: str, responses: list[str | Exception]) -> None:
        super().__init__(responses)
        self.provider = provider

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        result = await super().complete(messages, max_tokens=max_tokens)
        return LLMResult(**result.model_dump(exclude={"provider"}), provider=self.provider)


class GraphHarness:
    """Grafo com checkpointer em memória; guarda os eventos publicados."""

    def __init__(self, llm: Any, tools: Any, router: FakeRouter) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        from commerce_agents.infrastructure.agents.graph import GraphDeps, build_graph

        self.published: list[Any] = []

        async def publish(event: Any) -> None:
            self.published.append(event)

        self.graph = build_graph(
            GraphDeps(
                llm=llm,
                router=router,
                tools=tools,
                tokens=InMemoryTokenStore(),
                publish_event=publish,
                clock=FakeClock(),
                memory=FakeMemory(),
                new_key=key_factory(),
            ),
            checkpointer=MemorySaver(),
        )

    async def turn(self, conversation_id: str, text: str, *, message_id: str) -> dict[str, Any]:
        state: dict[str, Any] = await self.graph.ainvoke(
            turn_input(conversation_id, CUSTOMER, text, message_id=message_id),
            config={"configurable": {"thread_id": conversation_id}},
        )
        return state
