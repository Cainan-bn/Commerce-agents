"""Bordas do executor: confirmação ausente, falhas inesperadas e auditoria defensiva."""

import httpx
import pytest

from commerce_agents.application.dto.events import ToolInvoked
from commerce_agents.application.dto.tools import ToolError, ToolErrorCode
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.tools import SAMPLE_ARGUMENTS, issue_token

pytestmark = pytest.mark.unit


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="http://store")


async def test_irreversivel_sem_token_pede_confirmacao_sem_chamar_a_loja(
    make_unit_executor, transport
):
    arguments = {
        k: v for k, v in SAMPLE_ARGUMENTS["cancel_order"].items() if k != "confirmation_token"
    }

    result = await make_unit_executor().invoke("Pedidos", "cancel_order", arguments)

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_REQUIRED
    assert transport.requests == []


async def test_conversation_id_do_kwarg_completa_os_argumentos_e_a_auditoria(
    make_unit_executor, tokens: InMemoryTokenStore
):
    events: list[ToolInvoked] = []

    async def audit(event: ToolInvoked) -> None:
        events.append(event)

    arguments = {
        k: v for k, v in SAMPLE_ARGUMENTS["cancel_order"].items() if k != "conversation_id"
    }
    token = await issue_token(tokens, "cancel_order", arguments, conversation_id="conv-kwarg")
    arguments["confirmation_token"] = token
    handler = httpx.MockTransport(lambda r: httpx.Response(404))
    executor = make_unit_executor(audit=audit, client=_client(handler))

    result = await executor.invoke(
        "Pedidos", "cancel_order", arguments, conversation_id="conv-kwarg"
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND
    assert events[0].conversation_id == "conv-kwarg"


async def test_auditoria_sem_conversa_usa_unknown_e_trunca_valores(make_unit_executor):
    events: list[ToolInvoked] = []

    async def audit(event: ToolInvoked) -> None:
        events.append(event)

    executor = make_unit_executor(audit=audit)

    await executor.invoke(
        "CatalogoVendas",
        "quote_shipping",
        {"cep": "x" * 300, "items": [{"sku": "A", "qty": 1}], "n": 1, "flag": None},
    )

    event = events[0]
    assert event.conversation_id == "unknown"
    assert len(str(event.arguments["cep"])) == 200
    assert event.arguments["items"] == '[{"sku": "A", "qty": 1}]'
    assert event.arguments["n"] == 1


async def test_texto_livre_e_truncado_em_80_na_auditoria(make_unit_executor):
    events: list[ToolInvoked] = []

    async def audit(event: ToolInvoked) -> None:
        events.append(event)

    arguments = {**SAMPLE_ARGUMENTS["request_handoff"], "reason": "r" * 200}
    executor = make_unit_executor(audit=audit)

    await executor.invoke("Pedidos", "request_handoff", arguments)

    assert len(str(events[0].arguments["reason"])) == 80


async def test_falha_do_sink_de_auditoria_nao_vaza(make_unit_executor):
    async def broken(event: ToolInvoked) -> None:
        raise RuntimeError("fila fora do ar")

    executor = make_unit_executor(audit=broken)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "X"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.INVALID_ARGUMENT


async def test_excecao_inesperada_vira_upstream_error(make_unit_executor):
    async def handler(agent: str, arguments: object) -> ToolError:
        raise RuntimeError("segredo interno")

    executor = make_unit_executor(internal_handlers={"request_handoff": handler})

    result = await executor.invoke(
        "Pedidos", "request_handoff", SAMPLE_ARGUMENTS["request_handoff"]
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_ERROR
    assert "segredo" not in result.message


async def test_erro_de_transporte_vira_upstream_unavailable_retryable(make_unit_executor, sleeps):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusada", request=request)

    executor = make_unit_executor(client=_client(httpx.MockTransport(refuse)))

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True
    assert len(sleeps) == 2


async def test_422_sem_json_vira_invalid_argument(make_unit_executor):
    client = _client(httpx.MockTransport(lambda r: httpx.Response(422, text="<html>")))
    executor = make_unit_executor(client=client)

    result = await executor.invoke(
        "CatalogoVendas", "quote_shipping", SAMPLE_ARGUMENTS["quote_shipping"]
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.INVALID_ARGUMENT


async def test_200_com_corpo_fora_do_contrato_vira_upstream_error(make_unit_executor):
    client = _client(httpx.MockTransport(lambda r: httpx.Response(200, json={"inesperado": 1})))
    executor = make_unit_executor(client=client)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "O000001"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_ERROR
