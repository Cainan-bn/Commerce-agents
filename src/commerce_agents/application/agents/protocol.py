"""Protocolo do LLM (ADR 0013): `ToolCall` | `FinalAnswer` em JSON, sempre validado por schema."""

import json

from pydantic import TypeAdapter, ValidationError

from commerce_agents.application.agents.turn import AGENT_TOOL_KEY
from commerce_agents.application.dto.agents import FinalAnswer, ToolCall
from commerce_agents.application.dto.tools import AGENT_ALLOWLIST, INPUT_MODELS

_ACTION: TypeAdapter[ToolCall | FinalAnswer] = TypeAdapter(ToolCall | FinalAnswer)
_DECODER = json.JSONDecoder()


class ActionParseError(ValueError):
    """A saída do LLM não é uma ação válida do protocolo."""


def _first_object(text: str) -> object:
    """Primeiro objeto JSON do texto (o LLM pode cercá-lo de markdown ou prosa)."""
    start = text.find("{")
    while start != -1:
        try:
            value, _ = _DECODER.raw_decode(text, start)
        except (ValueError, RecursionError):
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise ActionParseError("Nenhum objeto JSON encontrado na resposta do LLM.")


def parse_agent_action(text: str) -> ToolCall | FinalAnswer:
    """Extrai e valida a ação. Qualquer defeito vira `ActionParseError`."""
    payload = _first_object(text)
    try:
        return _ACTION.validate_python(payload, strict=False)
    except ValidationError as error:
        raise ActionParseError("Ação do LLM fora do schema.") from error


def render_tool_catalog(agent_key: str) -> str:
    """Catálogo textual das ferramentas da allowlist do agente, com o JSON Schema dos inputs."""
    allowed = AGENT_ALLOWLIST[AGENT_TOOL_KEY[agent_key]]
    lines = []
    for name in sorted(allowed):
        schema = INPUT_MODELS[name].model_json_schema()
        properties = schema.get("properties", {})
        # Campos de confirmação são do código (ADR 0008): o LLM nunca os vê nem os preenche.
        visible = {
            field: spec
            for field, spec in properties.items()
            if field not in {"conversation_id", "confirmation_token", "idempotency_key"}
        }
        required = [f for f in schema.get("required", []) if f in visible]
        spec_json = json.dumps(
            {"properties": visible, "required": required}, ensure_ascii=False, sort_keys=True
        )
        lines.append(f"- {name}: {spec_json}")
    return "\n".join(lines)
