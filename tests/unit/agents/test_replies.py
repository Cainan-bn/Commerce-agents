"""Respostas por template em pt-BR (ADR 0013): nunca vêm do LLM e nunca expõem segredos."""

from datetime import UTC, datetime

import pytest

from commerce_agents.application.dto.confirmation import (
    ConfirmationOutcome,
    ConfirmationStatus,
    PendingAction,
)
from commerce_agents.application.dto.tools import CancelOrderOutput, ToolError, ToolErrorCode

pytestmark = pytest.mark.unit

TOKEN = "tok-secreto-123456789"
KEY = "idem-chave-secreta-01"


def _pending() -> PendingAction:
    return PendingAction(
        conversation_id="conv-1",
        agent="Pedidos",
        tool_name="cancel_order",
        arguments={"order_id": "O000014"},
        confirmation_token=TOKEN,
        idempotency_key=KEY,
        summary="Cancelar o pedido O000014. Essa ação não pode ser desfeita.",
        expires_at=datetime(2026, 11, 1, 12, 5, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "name",
    ["clarification", "refusal", "handoff_notice", "llm_unavailable", "no_source_found"],
)
def test_respostas_fixas_sao_pt_br_nao_vazias(name: str):
    from commerce_agents.application.agents import replies

    text = getattr(replies, name)()

    assert isinstance(text, str)
    assert text.strip()


def test_confirmation_outcome_cobre_os_cinco_status():
    from commerce_agents.application.agents.replies import confirmation_outcome

    outcomes = [
        ConfirmationOutcome(
            status=ConfirmationStatus.EXECUTED,
            result=CancelOrderOutput(
                order_id="O000014",
                status="cancelled",
                cancelled_at=datetime(2026, 11, 1, tzinfo=UTC),
            ),
        ),
        ConfirmationOutcome(
            status=ConfirmationStatus.FAILED,
            error=ToolError(code=ToolErrorCode.NOT_CANCELABLE, message="não cancelável"),
        ),
        ConfirmationOutcome(status=ConfirmationStatus.DECLINED),
        ConfirmationOutcome(status=ConfirmationStatus.UNCLEAR),
        ConfirmationOutcome(status=ConfirmationStatus.EXPIRED),
    ]

    texts = [confirmation_outcome(outcome, _pending()) for outcome in outcomes]

    assert all(text.strip() for text in texts)
    assert len(set(texts)) == 5


def test_confirmation_outcome_executado_menciona_pedido_sem_segredos():
    from commerce_agents.application.agents.replies import confirmation_outcome

    outcome = ConfirmationOutcome(
        status=ConfirmationStatus.EXECUTED,
        result=CancelOrderOutput(
            order_id="O000014", status="cancelled", cancelled_at=datetime(2026, 11, 1, tzinfo=UTC)
        ),
    )

    text = confirmation_outcome(outcome, _pending())

    assert "O000014" in text
    assert TOKEN not in text
    assert KEY not in text


@pytest.mark.parametrize("status", list(ConfirmationStatus))
def test_confirmation_outcome_nunca_expoe_token_nem_chave(status: ConfirmationStatus):
    from commerce_agents.application.agents.replies import confirmation_outcome

    outcome = ConfirmationOutcome(
        status=status,
        error=ToolError(code=ToolErrorCode.NOT_CANCELABLE, message="x")
        if status is ConfirmationStatus.FAILED
        else None,
        result=CancelOrderOutput(
            order_id="O000014", status="cancelled", cancelled_at=datetime(2026, 11, 1, tzinfo=UTC)
        )
        if status is ConfirmationStatus.EXECUTED
        else None,
    )

    text = confirmation_outcome(outcome, _pending())

    assert TOKEN not in text
    assert KEY not in text
