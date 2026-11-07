"""Registro estruturado da execução de um cenário (docs/architecture/evals.md)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnRecord(_Record):
    user_text: str
    reply: str
    agent: str
    intent: str
    confidence: float
    awaiting_confirmation: bool = False
    handoff: bool = False


class ToolCallRecord(_Record):
    """Chamada pedida pelo LLM; `arguments` auditados, sem token nem chave de idempotência."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    irreversible: bool = False
    executed: bool = True
    confirmed: bool = False
    ok: bool = True
    error_code: str | None = None
    result_excerpt: str = ""
    latency_ms: int = 0


class LLMCallRecord(_Record):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class Trace(_Record):
    scenario_id: str
    turns: list[TurnRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    handoff_events: list[str] = Field(default_factory=list)
    injection_flagged: bool = False
    policy_citations: list[str] = Field(default_factory=list)
    retrieved_chunks: list[str] = Field(default_factory=list)
    cost_usd: float | None = None
    infra_error: str | None = None
    customer_identified: bool = False
