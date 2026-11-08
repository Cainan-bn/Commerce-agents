"""Execução de um cenário contra o grafo real (docs/architecture/evals.md, ADR 0009/0015).

Ambiente isolado por cenário: a conversa tem id próprio, o checkpoint é `MemorySaver` e o estado
da loja volta ao seed em `EvalDeps.reset`. O cliente simulado é por regra, sem LLM.
"""

import json
import os
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from data.eval_scenarios_schema import IRREVERSIBLE_TOOLS, EvalScenario
from langgraph.checkpoint.memory import MemorySaver

from commerce_agents.application.agents.protocol import ActionParseError, parse_agent_action
from commerce_agents.application.dto.agents import ToolCall
from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.events import HandoffRequested, InboundMessageReceived
from commerce_agents.application.dto.tools import TOOL_SPECS
from commerce_agents.application.dto.views import IntentDecision, LLMMessage, LLMResult
from commerce_agents.application.ports.confirmation import (
    ConfirmationTokenStore,
    CustomerMemory,
    IdempotencyRegistry,
)
from commerce_agents.application.ports.llm import IntentRouter, LLMProvider
from commerce_agents.application.ports.tools import ToolInvoker
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.agents.graph import GraphDeps, build_graph
from commerce_agents.infrastructure.agents.service import ConversationService
from evals.pricing import estimate_cost_usd, load_pricing
from evals.trace import LLMCallRecord, ToolCallRecord, Trace, TurnRecord

MAX_TURNS = 8
CONFIRMATION_REPLY = "sim"
_HIDDEN_ARGS = frozenset({"confirmation_token", "idempotency_key", "conversation_id"})
_TOOL_RESULT = re.compile(r"<dados ferramenta>(.*?)</dados>", re.DOTALL)
_EXCERPT_CHARS = 600
_HIDDEN_RESULT_KEYS = _HIDDEN_ARGS | {"api_key"}
_NOT_EXECUTED = frozenset({"not_allowed", "invalid_argument"})
_UPSTREAM_CODES = frozenset({"upstream_timeout", "upstream_unavailable", "upstream_error"})

Publish = Callable[[StrictModel], Awaitable[None]]


@dataclass
class EvalDeps:
    """Dependências do ambiente de avaliação (fakes nos testes, reais em `make eval`)."""

    llm: LLMProvider
    router: IntentRouter
    tools: ToolInvoker
    tokens: ConfirmationTokenStore
    idempotency: IdempotencyRegistry
    publish: Publish
    clock: Callable[[], datetime]
    memory: CustomerMemory
    new_key: Callable[[], str]
    reset: Callable[[], None]
    model: str = ""
    temperature: float = 0.0
    llm_provider_name: str = ""
    api_key: str = ""


def _without_hidden(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_hidden(v) for k, v in value.items() if k not in _HIDDEN_RESULT_KEYS}
    if isinstance(value, list):
        return [_without_hidden(v) for v in value]
    return value


def _excerpt(body: Any) -> str:
    compact = json.dumps(_without_hidden(body), ensure_ascii=False, separators=(",", ":"))
    return compact[:_EXCERPT_CHARS]


class _Recorder:
    """Coleta o que o grafo faz durante o cenário, por observação dos pontos de injeção."""

    def __init__(self) -> None:
        self.llm_calls: list[LLMCallRecord] = []
        self.tool_calls: list[ToolCallRecord] = []
        self.handoff_events: list[str] = []
        self.issued_tokens: set[str] = set()
        self.rejected_tokens: set[str] = set()
        self.infra_error: str | None = None
        self._awaiting_result: ToolCallRecord | None = None
        self._requested_at = 0.0

    def fail(self, source: str, error: BaseException) -> None:
        if self.infra_error is None:
            self.infra_error = f"{source} indisponível: {type(error).__name__}: {str(error)[:200]}"

    # -- LLM ---------------------------------------------------------------------------------
    def on_llm_request(self, messages: list[LLMMessage]) -> None:
        """A última mensagem traz o resultado da ferramenta pedida na chamada anterior."""
        pending, self._awaiting_result = self._awaiting_result, None
        if pending is None or not messages:
            return
        match = _TOOL_RESULT.search(messages[-1].content)
        pending.latency_ms = int((time.monotonic() - self._requested_at) * 1000)
        if match is None:
            return
        try:
            body = json.loads(match.group(1))
        except ValueError:
            return
        pending.result_excerpt = _excerpt(body)
        code = body.get("code") if isinstance(body, dict) and body.get("ok") is False else None
        pending.ok = code is None
        pending.error_code = None if code is None else str(code)
        pending.executed = code not in _NOT_EXECUTED
        if code in _UPSTREAM_CODES:
            self.fail(f"ferramenta {pending.name}", RuntimeError(str(code)))

    def on_llm_result(self, result: LLMResult, latency_ms: int) -> None:
        self.llm_calls.append(
            LLMCallRecord(
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=latency_ms,
            )
        )
        try:
            action = parse_agent_action(result.content)
        except ActionParseError:
            return
        if not isinstance(action, ToolCall):
            return
        spec = TOOL_SPECS.get(action.tool)
        irreversible = bool(spec and spec.irreversible)
        record = ToolCallRecord(
            name=action.tool,
            arguments={k: v for k, v in action.arguments.items() if k not in _HIDDEN_ARGS},
            irreversible=irreversible,
            executed=not irreversible,
            confirmed=False,
        )
        self.tool_calls.append(record)
        # Irreversíveis só executam após a confirmação: o resultado não volta ao LLM.
        self._awaiting_result = None if irreversible else record
        self._requested_at = time.monotonic()

    # -- execução real de irreversíveis ----------------------------------------------------------
    def on_irreversible_executed(
        self, name: str, arguments: dict[str, Any], ok: bool, code: str | None, latency_ms: int
    ) -> None:
        token = str(arguments.get("confirmation_token", ""))
        record = next(
            (c for c in self.tool_calls if c.name == name and c.irreversible and not c.executed),
            None,
        )
        if record is None:
            record = ToolCallRecord(
                name=name,
                arguments={k: v for k, v in arguments.items() if k not in _HIDDEN_ARGS},
                irreversible=True,
            )
            self.tool_calls.append(record)
        record.executed = True
        record.confirmed = token in self.issued_tokens and token not in self.rejected_tokens
        record.ok = ok
        record.error_code = code
        record.latency_ms = latency_ms


class _RecordingLLM:
    def __init__(self, inner: LLMProvider, recorder: _Recorder) -> None:
        self._inner = inner
        self._recorder = recorder

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        self._recorder.on_llm_request(messages)
        started = time.monotonic()
        try:
            result = await self._inner.complete(messages, max_tokens=max_tokens)
        except Exception as error:
            self._recorder.fail("llm", error)
            raise
        self._recorder.on_llm_result(result, int((time.monotonic() - started) * 1000))
        return result


class _RecordingRouter:
    def __init__(self, inner: IntentRouter, recorder: _Recorder) -> None:
        self._inner = inner
        self._recorder = recorder

    async def route(self, text: str) -> IntentDecision:
        try:
            return await self._inner.route(text)
        except Exception as error:  # o grafo engole a falha; o harness a registra
            self._recorder.fail("roteador", error)
            raise


class _RecordingTools:
    def __init__(self, inner: ToolInvoker, recorder: _Recorder) -> None:
        self._inner = inner
        self._recorder = recorder

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Any,
        *,
        conversation_id: str | None = None,
    ) -> Any:
        started = time.monotonic()
        result = await self._inner.invoke(
            agent, tool_name, arguments, conversation_id=conversation_id
        )
        if tool_name in IRREVERSIBLE_TOOLS:
            code = getattr(result, "code", None)
            self._recorder.on_irreversible_executed(
                tool_name,
                dict(arguments),
                getattr(result, "ok", True) is not False,
                None if code is None else str(code),
                int((time.monotonic() - started) * 1000),
            )
        return result


class _RecordingTokens:
    def __init__(self, inner: ConfirmationTokenStore, recorder: _Recorder) -> None:
        self._inner = inner
        self._recorder = recorder

    async def issue(
        self, conversation_id: str, action: str, arguments_digest: str, ttl_seconds: int
    ) -> str:
        token = await self._inner.issue(conversation_id, action, arguments_digest, ttl_seconds)
        self._recorder.issued_tokens.add(token)
        return token

    async def consume(
        self, token: str, conversation_id: str, action: str, arguments_digest: str
    ) -> bool:
        consumed = await self._inner.consume(token, conversation_id, action, arguments_digest)
        if not consumed:
            self._recorder.rejected_tokens.add(token)
        return consumed


def _publisher(deps: EvalDeps, recorder: _Recorder) -> Publish:
    async def publish(event: StrictModel) -> None:
        if isinstance(event, HandoffRequested):
            recorder.handoff_events.append(event.reason)
        await deps.publish(event)

    return publish


def _cost_usd(deps: EvalDeps, recorder: _Recorder, before: float | None) -> float | None:
    total = getattr(deps.llm, "total_cost_usd", None)
    if isinstance(total, float) and before is not None:
        return total - before
    table = load_pricing()
    costs = [
        estimate_cost_usd(c.model, c.input_tokens, c.output_tokens, table)
        for c in recorder.llm_calls
    ]
    return None if not costs or any(c is None for c in costs) else sum(c or 0.0 for c in costs)


def _hook_router_failure(router: IntentRouter, recorder: _Recorder) -> Callable[[], None]:
    """Liga a queda do LLM no roteador ao `recorder`; roteadores sem `on_failure` ficam como são.

    A mensagem leva só o tipo do erro: o texto do provider pode ecoar dados do cliente.
    """
    if not hasattr(router, "on_failure"):
        return lambda: None
    previous = router.on_failure

    def restore() -> None:
        router.on_failure = previous

    router.on_failure = lambda error: recorder.fail("roteador", RuntimeError(type(error).__name__))
    return restore


async def run_scenario(scenario: EvalScenario, deps: EvalDeps) -> Trace:
    """Roda os turnos do cenário (máx. `MAX_TURNS`) e devolve o `Trace`; nunca levanta."""
    deps.reset()
    recorder = _Recorder()
    restore_router = _hook_router_failure(deps.router, recorder)
    graph = build_graph(
        GraphDeps(
            llm=_RecordingLLM(deps.llm, recorder),
            router=_RecordingRouter(deps.router, recorder),
            tools=_RecordingTools(deps.tools, recorder),
            tokens=_RecordingTokens(deps.tokens, recorder),
            publish_event=_publisher(deps, recorder),
            clock=deps.clock,
            memory=deps.memory,
            new_key=deps.new_key,
        ),
        checkpointer=MemorySaver(),
    )
    service = ConversationService(lambda: graph)
    customer_id = scenario.fixtures.get("customer_id", "")
    conversation_id = f"eval:{scenario.id}"
    config: Any = {"configurable": {"thread_id": conversation_id}}
    expected = scenario.expected
    confirmable = {t.name for t in expected.tools} & IRREVERSIBLE_TOOLS
    cost_before = getattr(deps.llm, "total_cost_usd", None)

    trace = Trace(scenario_id=scenario.id, customer_identified=bool(customer_id))
    queue = deque(scenario.turns)
    sent = 0
    try:
        while queue and sent < MAX_TURNS:
            text = queue.popleft()
            sent += 1
            event = InboundMessageReceived(
                message_id=f"{scenario.id}-m{sent}",
                conversation_id=conversation_id,
                channel=Channel.WEB,
                customer_external_id=customer_id or "anonimo",
                text=text,
                received_at=deps.clock(),
            )
            reply = await service.handle(event, customer_id)
            state = (await graph.aget_state(config)).values
            trace.turns.append(
                TurnRecord(
                    user_text=text,
                    reply=reply.text,
                    agent=reply.agent,
                    intent=str(state.get("intent", "")),
                    confidence=float(state.get("intent_confidence", 0.0)),
                    awaiting_confirmation=reply.awaiting_confirmation,
                    handoff=reply.handoff,
                )
            )
            trace.injection_flagged = trace.injection_flagged or bool(
                state.get("injection_flagged")
            )
            trace.retrieved_chunks = list(
                dict.fromkeys([*trace.retrieved_chunks, *state.get("retrieved_chunks", [])])
            )
            trace.policy_citations = list(
                dict.fromkeys([*trace.policy_citations, *reply.citations])
            )
            if recorder.infra_error:
                break
            if reply.awaiting_confirmation:
                proposed = (state.get("pending_action") or {}).get("tool_name")
                if proposed in expected.forbidden_tools:
                    break  # o cliente simulado não confirma o que o cenário proíbe
                if proposed in confirmable:
                    queue.appendleft(CONFIRMATION_REPLY)
    except Exception as error:
        recorder.fail("harness", error)

    trace.tool_calls = recorder.tool_calls
    trace.llm_calls = recorder.llm_calls
    trace.handoff_events = recorder.handoff_events
    restore_router()
    trace.infra_error = recorder.infra_error
    trace.cost_usd = _cost_usd(deps, recorder, cost_before)
    return trace


def build_real_deps(
    *,
    llm: LLMProvider,
    router: IntentRouter | None = None,
    model: str = "",
    llm_provider_name: str = "",
    temperature: float = 0.0,
) -> EvalDeps:
    """Ambiente real: `mock_store` ASGI em memória, `ToolExecutor` real e retriever do Postgres."""
    import itertools
    from datetime import UTC

    from mock_store.main import create_app

    from commerce_agents.infrastructure.agents.handlers import make_search_policies_handler
    from commerce_agents.infrastructure.agents.router import LLMIntentRouter
    from commerce_agents.infrastructure.mcp.executor import ToolExecutor
    from commerce_agents.infrastructure.mcp.memory import (
        InMemoryIdempotencyRegistry,
        InMemoryTokenStore,
    )
    from commerce_agents.infrastructure.persistence.database import (
        create_engine,
        create_session_factory,
    )
    from commerce_agents.infrastructure.persistence.migrate import sync_url_from_env
    from commerce_agents.infrastructure.rag.embedder import FastEmbedEmbedder
    from commerce_agents.infrastructure.rag.retriever import HybridPolicyRetriever

    app = create_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://store")
    tokens = InMemoryTokenStore()
    idempotency = InMemoryIdempotencyRegistry()
    engine = create_engine(sync_url_from_env().replace("+psycopg", "+asyncpg"))
    retriever = HybridPolicyRetriever(create_session_factory(engine), FastEmbedEmbedder())
    executor = ToolExecutor(
        client=client,
        tokens=tokens,
        idempotency=idempotency,
        internal_handlers={"search_policies": make_search_policies_handler(retriever)},
    )
    counter = itertools.count(1)

    async def publish(event: StrictModel) -> None:
        return None

    class _Memory:
        async def get_preferences(self, customer_id: str) -> dict[str, str]:
            return {}

        async def set_preference(self, customer_id: str, key: str, value: str) -> None:
            return None

    return EvalDeps(
        llm=llm,
        router=router or LLMIntentRouter(llm),
        tools=executor,
        tokens=tokens,
        idempotency=idempotency,
        publish=publish,
        clock=lambda: datetime.now(UTC),
        memory=_Memory(),
        new_key=lambda: f"idem-eval-{os.getpid()}-{next(counter):06d}",
        reset=app.state.store.reload,
        model=model,
        temperature=temperature,
        llm_provider_name=llm_provider_name,
    )
