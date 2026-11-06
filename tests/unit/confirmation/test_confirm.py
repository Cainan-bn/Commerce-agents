"""ConfirmIrreversibleAction: o 'sim' do cliente executa só a proposta pendente (ADR 0008/0011)."""

from typing import Any

import pytest

from commerce_agents.application.dto.confirmation import ConfirmationStatus
from commerce_agents.application.dto.events import IrreversibleActionConfirmed
from commerce_agents.application.dto.tools import CancelOrderOutput, ToolError, ToolErrorCode
from tests.fakes.clock import BASE_TIME, FakeClock
from tests.fakes.invoker import FakeToolInvoker, RecordingPublisher
from tests.fakes.tools import CONVERSATION_ID

pytestmark = pytest.mark.unit

CANCELLED = CancelOrderOutput(order_id="O000014", status="cancelled", cancelled_at=BASE_TIME)
TOOL_ERROR = ToolError(code=ToolErrorCode.NOT_CANCELABLE, message="pedido não cancelável")


async def _pending(make_propose: Any) -> Any:
    propose = make_propose()
    return await propose.execute(
        CONVERSATION_ID, "Pedidos", "cancel_order", {"order_id": "O000014"}
    )


async def test_sim_executa_uma_vez_com_argumentos_da_proposta(
    make_propose, make_confirm, invoker: FakeToolInvoker, publisher: RecordingPublisher
):
    invoker.outcome = CANCELLED
    pending = await _pending(make_propose)
    confirm = make_confirm(invoker, publisher)

    outcome = await confirm.execute(pending, "sim")

    assert outcome.status is ConfirmationStatus.EXECUTED
    assert outcome.result == CANCELLED
    assert len(invoker.calls) == 1
    call = invoker.calls[0]
    assert call["agent"] == "Pedidos"
    assert call["tool_name"] == "cancel_order"
    assert call["arguments"]["order_id"] == "O000014"
    assert call["arguments"]["conversation_id"] == CONVERSATION_ID
    assert call["arguments"]["confirmation_token"] == pending.confirmation_token
    assert call["arguments"]["idempotency_key"] == pending.idempotency_key


async def test_evento_confirmado_e_publicado_antes_da_ferramenta(
    make_propose,
    make_confirm,
    invoker: FakeToolInvoker,
    publisher: RecordingPublisher,
    log,
    clock: FakeClock,
):
    invoker.outcome = CANCELLED
    pending = await _pending(make_propose)
    confirm = make_confirm(invoker, publisher)

    await confirm.execute(pending, "sim")

    assert log == [("event", "cancel_order"), ("tool", "cancel_order")]
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, IrreversibleActionConfirmed)
    assert event.conversation_id == CONVERSATION_ID
    assert event.action == "cancel_order"
    assert event.idempotency_key == pending.idempotency_key
    assert event.confirmed_at == clock()
    assert event.confirmation_token_id != pending.confirmation_token
    assert pending.confirmation_token not in event.model_dump_json()


async def test_negativa_recusa_sem_invocar_nem_publicar(
    make_propose, make_confirm, invoker, publisher
):
    pending = await _pending(make_propose)
    confirm = make_confirm(invoker, publisher)

    outcome = await confirm.execute(pending, "não quero")

    assert outcome.status is ConfirmationStatus.DECLINED
    assert invoker.calls == []
    assert publisher.events == []


async def test_ambigua_pede_de_novo_sem_invocar(make_propose, make_confirm, invoker, publisher):
    pending = await _pending(make_propose)
    confirm = make_confirm(invoker, publisher)

    outcome = await confirm.execute(pending, "talvez")

    assert outcome.status is ConfirmationStatus.UNCLEAR
    assert invoker.calls == []
    assert publisher.events == []


async def test_expirada_nao_executa_mesmo_com_sim(
    make_propose, make_confirm, invoker, publisher, clock: FakeClock
):
    pending = await _pending(make_propose)
    clock.advance(301)
    confirm = make_confirm(invoker, publisher)

    outcome = await confirm.execute(pending, "sim")

    assert outcome.status is ConfirmationStatus.EXPIRED
    assert invoker.calls == []
    assert publisher.events == []


async def test_no_instante_de_expiracao_ja_esta_expirada(
    make_propose, make_confirm, invoker, publisher, clock: FakeClock
):
    pending = await _pending(make_propose)
    clock.now = pending.expires_at
    confirm = make_confirm(invoker, publisher)

    outcome = await confirm.execute(pending, "sim")

    assert outcome.status is ConfirmationStatus.EXPIRED
    assert invoker.calls == []


async def test_toolerror_da_ferramenta_vira_failed_com_evento_ja_publicado(
    make_propose, make_confirm, invoker, publisher, log
):
    invoker.outcome = TOOL_ERROR
    pending = await _pending(make_propose)
    confirm = make_confirm(invoker, publisher)

    outcome = await confirm.execute(pending, "sim")

    assert outcome.status is ConfirmationStatus.FAILED
    assert outcome.error == TOOL_ERROR
    assert len(publisher.events) == 1
    assert log[0] == ("event", "cancel_order")


async def test_reexecutar_a_mesma_proposta_reutiliza_token_e_chave(
    make_propose, make_confirm, invoker, publisher
):
    invoker.outcome = TOOL_ERROR
    pending = await _pending(make_propose)
    confirm = make_confirm(invoker, publisher)

    await confirm.execute(pending, "sim")
    await confirm.execute(pending, "sim")

    assert len(invoker.calls) == 2
    first, second = invoker.calls
    assert first["arguments"]["confirmation_token"] == second["arguments"]["confirmation_token"]
    assert first["arguments"]["idempotency_key"] == second["arguments"]["idempotency_key"]


async def test_sem_proposta_pendente_nada_executa(make_confirm, invoker, publisher):
    confirm = make_confirm(invoker, publisher)

    with pytest.raises((TypeError, AttributeError, ValueError)):
        await confirm.execute(None, "sim")

    assert invoker.calls == []
    assert publisher.events == []
