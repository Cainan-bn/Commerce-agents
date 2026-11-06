"""Casos de borda dos módulos puros do orquestrador (cobertura dos ramos de falha)."""

from datetime import UTC, datetime

import pytest

from commerce_agents.application.agents.protocol import ActionParseError, parse_agent_action
from commerce_agents.application.agents.replies import confirmation_outcome
from commerce_agents.application.agents.scoped_invoker import ScopedToolInvoker
from commerce_agents.application.dto.confirmation import (
    ConfirmationOutcome,
    ConfirmationStatus,
    PendingAction,
)
from commerce_agents.application.dto.tools import ToolError, ToolErrorCode

pytestmark = pytest.mark.unit


def _pending(tool: str) -> PendingAction:
    return PendingAction(
        conversation_id="conv-1",
        agent="PosVenda",
        tool_name=tool,
        arguments={"order_id": "O000014"},
        confirmation_token="tok-secreto-123456789",
        idempotency_key="idem-chave-secreta-01",
        summary="Resumo.",
        expires_at=datetime(2026, 11, 1, 12, 5, tzinfo=UTC),
    )


def test_json_que_nao_e_objeto_e_ignorado():
    with pytest.raises(ActionParseError):
        parse_agent_action("[1, 2] e depois {sem fechar")


def test_objeto_json_apos_lixo_e_encontrado():
    action = parse_agent_action('{ruim} {"type": "final", "text": "Oi"}')

    assert action.type == "final"


def test_devolucao_executada_e_falha_generica():
    executed = ConfirmationOutcome(status=ConfirmationStatus.EXECUTED)
    failed = ConfirmationOutcome(status=ConfirmationStatus.FAILED)
    coded = ConfirmationOutcome(
        status=ConfirmationStatus.FAILED,
        error=ToolError(code=ToolErrorCode.UPSTREAM_ERROR, message="x"),
    )

    assert "devolução" in confirmation_outcome(executed, _pending("open_return"))
    assert confirmation_outcome(failed, _pending("cancel_order")) == confirmation_outcome(
        coded, _pending("cancel_order")
    )


async def test_argumento_order_id_ausente_segue_para_o_executor():
    class Inner:
        calls: list[str] = []

        async def invoke(self, agent, tool_name, arguments, *, conversation_id=None):  # type: ignore[no-untyped-def]
            self.calls.append(tool_name)
            return ToolError(code=ToolErrorCode.INVALID_ARGUMENT, message="falta order_id")

    inner = Inner()
    result = await ScopedToolInvoker(inner, "C0001").invoke("Pedidos", "get_order_status", {})

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.INVALID_ARGUMENT
    assert inner.calls == ["get_order_status"]
