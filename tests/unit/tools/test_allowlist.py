"""Allowlist por agente aplicada no executor, fora do LLM (ADR 0010)."""

import pytest

from commerce_agents.application.dto.tools import (
    AGENT_ALLOWLIST,
    TOOL_SPECS,
    ToolError,
    ToolErrorCode,
)
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import SAMPLE_ARGUMENTS

pytestmark = pytest.mark.unit

FORBIDDEN_PAIRS = [
    (agent, tool)
    for agent in AGENT_ALLOWLIST
    for tool in TOOL_SPECS
    if tool not in AGENT_ALLOWLIST[agent]
] + [("Desconhecido", tool) for tool in TOOL_SPECS]

ALLOWED_READ_PAIRS = [
    (agent, tool)
    for agent, tools in AGENT_ALLOWLIST.items()
    for tool in sorted(tools)
    if not TOOL_SPECS[tool].irreversible and TOOL_SPECS[tool].server != "internal"
]


@pytest.mark.parametrize(("agent", "tool_name"), FORBIDDEN_PAIRS)
async def test_fora_da_allowlist_vira_not_allowed_sem_requisicao(
    make_unit_executor, transport: RecordingTransport, agent: str, tool_name: str
):
    executor = make_unit_executor()

    result = await executor.invoke(agent, tool_name, SAMPLE_ARGUMENTS[tool_name])

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_ALLOWED
    assert transport.requests == []


@pytest.mark.parametrize(("agent", "tool_name"), ALLOWED_READ_PAIRS)
async def test_permitido_chega_a_loja(
    make_unit_executor, transport: RecordingTransport, agent: str, tool_name: str
):
    executor = make_unit_executor()

    result = await executor.invoke(agent, tool_name, SAMPLE_ARGUMENTS[tool_name])

    assert not (isinstance(result, ToolError) and result.code is ToolErrorCode.NOT_ALLOWED)
    assert len(transport.requests) >= 1
