"""Schema Pydantic v2 estrito dos cenários de avaliação (data/README.md).

O vocabulário (intenção, agente, ferramenta e argumentos) vem de `application`: um cenário só
pode esperar o que o sistema tem.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from commerce_agents.application.agents.turn import AGENT_FOR_INTENT
from commerce_agents.application.dto.agents import Intent
from commerce_agents.application.dto.tools import INPUT_MODELS, TOOL_SPECS

SPLITS: tuple[str, ...] = ("dev", "holdout")

CATEGORIES: tuple[str, ...] = (
    "pedidos",
    "catalogo",
    "politicas",
    "pos_venda",
    "injection",
    "ambiguo",
    "handoff",
)

TOOLS: tuple[str, ...] = tuple(TOOL_SPECS)
INTENTS: tuple[str, ...] = tuple(intent.value for intent in Intent)
AGENTS: tuple[str, ...] = tuple(sorted(set(AGENT_FOR_INTENT.values())))

IRREVERSIBLE_TOOLS: frozenset[str] = frozenset({"cancel_order", "open_return"})

Split = Literal["dev", "holdout"]
Category = Literal[
    "pedidos",
    "catalogo",
    "politicas",
    "pos_venda",
    "injection",
    "ambiguo",
    "handoff",
]
Outcome = Literal["resolved", "handoff", "refused", "clarified"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


def _known(kind: str, value: str, valid: tuple[str, ...]) -> str:
    if value not in valid:
        raise ValueError(f"{kind} desconhecido: {value!r}; válidos: {', '.join(valid)}")
    return value


class ToolCall(StrictModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _tool_and_args_exist(self) -> ToolCall:
        _known("ferramenta", self.name, TOOLS)
        fields = INPUT_MODELS[self.name].model_fields
        unknown = sorted(set(self.args) - set(fields))
        if unknown:
            raise ValueError(
                f"argumentos desconhecidos em {self.name}: {', '.join(unknown)}; "
                f"válidos: {', '.join(fields)}"
            )
        return self


class Expected(StrictModel):
    intent: str
    agent: str
    tools: list[ToolCall] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    irreversible_without_confirmation: bool
    must_mention: list[str] = Field(default_factory=list)
    outcome: Outcome
    citations_required: bool = False
    leaks: Literal["forbidden"] | None = None

    @field_validator("intent")
    @classmethod
    def _intent_exists(cls, value: str) -> str:
        return _known("intenção", value, INTENTS)

    @field_validator("agent")
    @classmethod
    def _agent_exists(cls, value: str) -> str:
        return _known("agente", value, AGENTS)

    @field_validator("forbidden_tools")
    @classmethod
    def _forbidden_tools_exist(cls, value: list[str]) -> list[str]:
        for name in value:
            _known("ferramenta", name, TOOLS)
        return value


class EvalScenario(StrictModel):
    id: str
    split: Split
    category: Category
    persona: str
    goal: str
    fixtures: dict[str, str] = Field(default_factory=dict)
    turns: list[str]
    expected: Expected
    notes: str | None = None
