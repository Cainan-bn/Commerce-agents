"""ToolInvoked: uma auditoria por invoke, sem token nem segredos nos argumentos (ADR 0008)."""

import pytest

from commerce_agents.application.dto.events import ToolInvoked
from commerce_agents.application.dto.tools import ToolError, ToolErrorCode
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import irreversible_arguments, issue_token

pytestmark = pytest.mark.unit


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ToolInvoked] = []

    async def __call__(self, event: ToolInvoked) -> None:
        self.events.append(event)


async def test_leitura_com_entrada_invalida_audita_uma_vez_como_falha(
    make_unit_executor, transport: RecordingTransport
):
    recorder = _Recorder()
    executor = make_unit_executor(audit=recorder)

    result = await executor.invoke("Pedidos", "get_order_status", {"order_id": "X"})

    assert isinstance(result, ToolError)
    assert len(recorder.events) == 1
    assert recorder.events[0].irreversible is False
    assert recorder.events[0].succeeded is False
    assert transport.requests == []


async def test_irreversivel_sem_token_audita_como_falha_sem_token_nos_argumentos(
    make_unit_executor, tokens: InMemoryTokenStore
):
    recorder = _Recorder()
    executor = make_unit_executor(audit=recorder, tokens=tokens)
    arguments = irreversible_arguments(
        "cancel_order", "token-secreto-falso", "idem-audit-0001", order_id="O000014"
    )

    result = await executor.invoke("Pedidos", "cancel_order", arguments)

    assert isinstance(result, ToolError)
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.irreversible is True
    assert event.succeeded is False
    assert "confirmation_token" not in event.arguments
    assert "token-secreto-falso" not in repr(event)


async def test_allowlist_negada_ainda_audita_uma_vez(make_unit_executor):
    recorder = _Recorder()
    executor = make_unit_executor(audit=recorder)

    result = await executor.invoke("Politicas", "cancel_order", {"order_id": "O000014"})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_ALLOWED
    assert len(recorder.events) == 1
    assert recorder.events[0].succeeded is False


async def test_sem_audit_o_executor_funciona(make_unit_executor, tokens: InMemoryTokenStore):
    executor = make_unit_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})

    result = await executor.invoke(
        "Pedidos",
        "cancel_order",
        irreversible_arguments("cancel_order", token, "idem-noaud-0001", order_id="O000014"),
    )

    assert result.ok is True
