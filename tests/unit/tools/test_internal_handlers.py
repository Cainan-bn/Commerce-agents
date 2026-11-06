"""Ferramentas internas (search_policies, request_handoff) delegam ao handler injetado."""

import httpx
import pytest

from commerce_agents.application.dto.tools import (
    RequestHandoffInput,
    RequestHandoffOutput,
    SearchPoliciesInput,
    SearchPoliciesOutput,
    ToolError,
    ToolErrorCode,
)
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import SAMPLE_ARGUMENTS

pytestmark = pytest.mark.unit


async def test_search_policies_delega_ao_handler_com_input_validado(
    make_unit_executor, transport: RecordingTransport
):
    calls: list[tuple[str, object]] = []
    expected = SearchPoliciesOutput(chunks=())

    async def handler(agent: str, arguments: object) -> SearchPoliciesOutput:
        calls.append((agent, arguments))
        return expected

    executor = make_unit_executor(internal_handlers={"search_policies": handler})

    result = await executor.invoke(
        "Politicas", "search_policies", SAMPLE_ARGUMENTS["search_policies"]
    )

    assert result is expected
    assert len(calls) == 1
    assert isinstance(calls[0][1], SearchPoliciesInput)
    assert calls[0][1].query == SAMPLE_ARGUMENTS["search_policies"]["query"]
    assert transport.requests == []


async def test_request_handoff_repassa_toolerror_do_handler(
    make_unit_executor, transport: RecordingTransport
):
    failure = ToolError(code=ToolErrorCode.UPSTREAM_ERROR, message="fila indisponível")

    async def handler(agent: str, arguments: object) -> ToolError:
        assert isinstance(arguments, RequestHandoffInput)
        return failure

    executor = make_unit_executor(internal_handlers={"request_handoff": handler})

    result = await executor.invoke(
        "Pedidos", "request_handoff", SAMPLE_ARGUMENTS["request_handoff"]
    )

    assert result == failure
    assert transport.requests == []


async def test_request_handoff_sucesso_devolve_saida_do_handler(make_unit_executor):
    async def handler(agent: str, arguments: object) -> RequestHandoffOutput:
        return RequestHandoffOutput(handoff_id="H-1")

    executor = make_unit_executor(internal_handlers={"request_handoff": handler})

    result = await executor.invoke(
        "Pedidos", "request_handoff", SAMPLE_ARGUMENTS["request_handoff"]
    )

    assert isinstance(result, RequestHandoffOutput)
    assert result.handoff_id == "H-1"


@pytest.mark.parametrize(
    ("agent", "tool_name"), [("Politicas", "search_policies"), ("Pedidos", "request_handoff")]
)
async def test_sem_handler_devolve_not_found(
    make_unit_executor, transport: RecordingTransport, agent: str, tool_name: str
):
    executor = make_unit_executor(internal_handlers={})

    result = await executor.invoke(agent, tool_name, SAMPLE_ARGUMENTS[tool_name])

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND
    assert transport.requests == []


def test_transporte_de_teste_nao_depende_de_rede():
    assert issubclass(RecordingTransport, httpx.AsyncBaseTransport)
