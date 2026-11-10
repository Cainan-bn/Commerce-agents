"""Instrumentação OpenTelemetry do atendimento (ADR 0018): só a API; o SDK vem da composição.

Sem SDK instalado (`interfaces.telemetry.setup_telemetry`) tudo aqui é no-op. Privacidade: spans,
métricas e logs levam só identificadores e números; prompt e resposta só entram nos spans de LLM
com `OTEL_CAPTURE_CONTENT=true`, e nunca token de confirmação nem chave (o LLM não os vê).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.util.types import AttributeValue

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.tools import ToolError
from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import (
    LLMBadRequestError,
    LLMProvider,
    LLMUnavailableError,
)
from commerce_agents.application.ports.tools import ToolInvoker

_SCOPE = "commerce_agents"
_tracer = trace.get_tracer(_SCOPE)
_meter = metrics.get_meter(_SCOPE)
_propagator = TraceContextTextMapPropagator()

# Limites dos histogramas na escala das metas: os padrões do SDK (0, 5, 10, ...) tornam o p95
# inútil. A meta do turno (4 s) é um limite exato.
LATENCY_BUCKETS_S = (0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 30)
TOOL_LATENCY_BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1, 2.5)
TURN_COST_BUCKETS_USD = (0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1)

TURN_DURATION = _meter.create_histogram(
    "conversation.turn.duration",
    unit="s",
    description="Latência de um turno do grafo",
    explicit_bucket_boundaries_advisory=LATENCY_BUCKETS_S,
)
LLM_CALLS = _meter.create_counter(
    "llm.calls", description="Chamadas de LLM do especialista por provider e resultado"
)
LLM_DURATION = _meter.create_histogram(
    "llm.duration",
    unit="s",
    description="Latência do LLM",
    explicit_bucket_boundaries_advisory=LATENCY_BUCKETS_S,
)
LLM_TOKENS = _meter.create_counter("llm.tokens", description="Tokens por provider e direção")
LLM_COST = _meter.create_counter(
    "llm.cost.usd", unit="USD", description="Custo conhecido das chamadas por provider e modelo"
)
TURN_COST = _meter.create_histogram(
    "conversation.turn.cost",
    unit="USD",
    description="Custo do LLM por turno de custo conhecido",
    explicit_bucket_boundaries_advisory=TURN_COST_BUCKETS_USD,
)
TOOL_DURATION = _meter.create_histogram(
    "tool.duration",
    unit="s",
    description="Latência das ferramentas por nome e resultado",
    explicit_bucket_boundaries_advisory=TOOL_LATENCY_BUCKETS_S,
)
HANDOFFS = _meter.create_counter("handoff.requested", description="Handoffs por motivo")
CIRCUIT_OPENED = _meter.create_counter(
    "llm.circuit.opened", description="Aberturas do circuit breaker por provider"
)
FALLBACK_USED = _meter.create_counter(
    "llm.fallback.used", description="Respostas dadas por um provider de fallback"
)

# Motivos de handoff fixados em código; o resto (texto do LLM em request_handoff) vira um só.
_HANDOFF_REASONS = frozenset(
    {
        "cliente_pediu_atendente",
        "llm_indisponivel",
        "saida_invalida_do_llm",
        "limite_de_passos",
        "resposta_sem_fonte",
        "orcamento_de_tokens_esgotado",
        "solicitado",
    }
)
_OTHER_HANDOFF = "pedido_do_agente"
_UNKNOWN = "desconhecido"

# Identificadores do turno corrente: vão em todo span e nos logs.
_turn: ContextVar[Mapping[str, str] | None] = ContextVar("telemetry_turn", default=None)
# Custo de cada chamada de LLM do turno corrente (`None` = desconhecido).
_turn_costs: ContextVar[list[float | None] | None] = ContextVar(
    "telemetry_turn_costs", default=None
)


def capture_content() -> bool:
    """Captura de prompt/resposta, só para desenvolvimento (lida a cada chamada)."""
    return os.environ.get("OTEL_CAPTURE_CONTENT", "").strip().lower() == "true"


@contextmanager
def span(
    name: str,
    attributes: Mapping[str, AttributeValue] | None = None,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    context: Context | None = None,
) -> Iterator[Span]:
    """Span com os identificadores do turno corrente mais `attributes`."""
    with _tracer.start_as_current_span(
        name,
        context=context,
        kind=kind,
        attributes={**(_turn.get() or {}), **(attributes or {})},
    ) as current:
        yield current


@contextmanager
def turn_span(state: Mapping[str, Any]) -> Iterator[Span]:
    """Span raiz `conversation.turn` e histograma de latência do turno."""
    ids = {
        "conversation_id": str(state.get("conversation_id", "")),
        "channel": str(state.get("channel", "")),
        "message_id": str(state.get("message_id", "")),
    }
    token = _turn.set(ids)
    costs: list[float | None] = []
    costs_token = _turn_costs.set(costs)
    started = time.monotonic()
    try:
        with span("conversation.turn") as root:
            try:
                yield root
            finally:
                _record_turn_cost(root, costs, ids["channel"])
    finally:
        TURN_DURATION.record(time.monotonic() - started, {"channel": ids["channel"]})
        _turn_costs.reset(costs_token)
        _turn.reset(token)


def _record_turn_cost(root: Span, costs: Sequence[float | None], channel: str) -> None:
    """Soma do turno só quando todas as chamadas têm custo conhecido (sem chamadas, nada)."""
    if not costs or any(cost is None for cost in costs):
        return
    total = sum(cost or 0.0 for cost in costs)
    root.set_attribute("conversation.turn.cost_usd", total)
    TURN_COST.record(total, {"channel": channel})


def record_handoff(reason: str) -> None:
    HANDOFFS.add(1, {"reason": reason if reason in _HANDOFF_REASONS else _OTHER_HANDOFF})


def _fail(current: Span, error: BaseException) -> None:
    # Só o tipo: a mensagem do provider pode ecoar dados do cliente.
    current.set_status(Status(StatusCode.ERROR, type(error).__name__))


def _messages_json(messages: Sequence[LLMMessage]) -> str:
    return json.dumps(
        [{"role": m.role, "content": m.content} for m in messages], ensure_ascii=False
    )


class TracedLLM:
    """Span `llm.complete` (convenções `gen_ai.*`) e métricas por chamada ao provider."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        fallback_name = str(getattr(self._inner, "name", "") or _UNKNOWN)
        started = time.monotonic()
        with span(
            "llm.complete",
            {"gen_ai.operation.name": "chat", "gen_ai.request.max_tokens": max_tokens},
            kind=SpanKind.CLIENT,
        ) as current:
            if capture_content():
                current.add_event("gen_ai.prompt", {"gen_ai.prompt": _messages_json(messages)})
            try:
                result = await self._inner.complete(messages, max_tokens=max_tokens)
            except Exception as error:
                outcome = (
                    "unavailable"
                    if isinstance(error, LLMUnavailableError)
                    else "bad_request"
                    if isinstance(error, LLMBadRequestError)
                    else "error"
                )
                _fail(current, error)
                LLM_CALLS.add(1, {"provider": fallback_name, "outcome": outcome})
                raise
            provider = result.provider or fallback_name
            current.set_attributes(
                {
                    "gen_ai.request.model": str(getattr(self._inner, "model", "") or result.model),
                    "gen_ai.response.model": result.model,
                    "gen_ai.provider.name": provider,
                    "gen_ai.usage.input_tokens": result.input_tokens,
                    "gen_ai.usage.output_tokens": result.output_tokens,
                }
            )
            if result.cost_usd is not None:
                current.set_attribute("gen_ai.usage.cost_usd", result.cost_usd)
            if capture_content():
                current.add_event("gen_ai.completion", {"gen_ai.completion": result.content})
        costs = _turn_costs.get()
        if costs is not None:
            costs.append(result.cost_usd)
        attrs = {"provider": provider}
        LLM_CALLS.add(1, {**attrs, "outcome": "ok"})
        LLM_DURATION.record(time.monotonic() - started, attrs)
        LLM_TOKENS.add(result.input_tokens, {**attrs, "direction": "input"})
        LLM_TOKENS.add(result.output_tokens, {**attrs, "direction": "output"})
        if result.cost_usd is not None:
            LLM_COST.add(result.cost_usd, {**attrs, "model": result.model})
        return result


class TracedToolInvoker:
    """Span `tool.invoke` por ferramenta: nome, ok e código do erro (nunca os argumentos)."""

    def __init__(self, inner: ToolInvoker) -> None:
        self._inner = inner

    async def invoke(
        self,
        agent: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> StrictModel | ToolError:
        started = time.monotonic()
        with span("tool.invoke", {"tool.name": tool_name}) as current:
            result = await self._inner.invoke(
                agent, tool_name, arguments, conversation_id=conversation_id
            )
            ok = not isinstance(result, ToolError)
            current.set_attribute("tool.ok", ok)
            if isinstance(result, ToolError):
                current.set_attribute("tool.error_code", result.code.value)
        TOOL_DURATION.record(time.monotonic() - started, {"tool.name": tool_name, "tool.ok": ok})
        return result


# ------------------------------------------------------------------ propagação pelo broker


def inject_headers() -> list[tuple[str, bytes]]:
    """Headers W3C (`traceparent`) do contexto corrente, no formato do aiokafka."""
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return [(key, value.encode()) for key, value in carrier.items()]


def current_traceparent() -> str | None:
    """`traceparent` W3C do contexto corrente (gravado no outbox); `None` sem span ativo."""
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


@contextmanager
def outbox_publish_span(traceparent: str | None) -> Iterator[None]:
    """Contexto da publicação de uma linha do outbox: span `outbox.publish` filho do turno que a
    gravou; sem `traceparent`, contexto vazio (nunca o do laço do relay)."""
    if traceparent is None:
        token = otel_context.attach(Context())
        try:
            yield
        finally:
            otel_context.detach(token)
        return
    parent = _propagator.extract({"traceparent": traceparent})
    with _tracer.start_as_current_span("outbox.publish", context=parent, kind=SpanKind.PRODUCER):
        yield


@contextmanager
def channel_send_span(conversation_id: str, channel: str, message_id: str) -> Iterator[Span]:
    """Span `channel.send` da entrega ao cliente: só identificadores, nunca o texto."""
    with span(
        "channel.send",
        {"conversation_id": conversation_id, "channel": channel, "message_id": message_id},
        kind=SpanKind.CLIENT,
    ) as current:
        yield current


@contextmanager
def consumer_span(topic: str, headers: Sequence[tuple[str, bytes]] | None) -> Iterator[Span]:
    """Span do consumo cujo pai vem dos headers da mensagem (continua o trace do publicador)."""
    carrier = {
        key: value.decode(errors="replace") if isinstance(value, bytes) else str(value)
        for key, value in headers or ()
    }
    with span(
        f"{topic} process",
        {"messaging.destination.name": topic},
        kind=SpanKind.CONSUMER,
        context=_propagator.extract(carrier),
    ) as current:
        yield current


# ------------------------------------------------------------------------------------ logs


class TraceContextLogFilter(logging.Filter):
    """Acrescenta `trace_id` e `conversation_id` ao registro de log (nunca texto do cliente)."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = f"{context.trace_id:032x}" if context.is_valid else "-"
        record.conversation_id = (_turn.get() or {}).get("conversation_id") or "-"
        return True
