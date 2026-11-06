"""Ferramentas irreversíveis contra o mock_store (ADR 0008 e 0011)."""

import httpx
import pytest

from commerce_agents.application.dto.events import ToolInvoked
from commerce_agents.application.dto.tools import (
    CancelOrderOutput,
    OpenReturnOutput,
    ToolError,
    ToolErrorCode,
    action_digest,
)
from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import (
    STORE_URL,
    irreversible_arguments,
    issue_token,
)

pytestmark = pytest.mark.contract


def _cancel_args(token: str, key: str, order_id: str = "O000014") -> dict[str, object]:
    return irreversible_arguments("cancel_order", token, key, order_id=order_id)


def _return_args(token: str, key: str, reason: str = "tamanho errado") -> dict[str, object]:
    return irreversible_arguments(
        "open_return", token, key, order_id="O000001", sku="P0168-GG-AZUL", reason=reason
    )


async def test_sem_token_recusa_e_nao_chama_a_loja(
    make_executor, transport: RecordingTransport, store_app
):
    executor = make_executor()
    arguments = _cancel_args("token-forjado", "idem-forjado-01")

    result = await executor.invoke("Pedidos", "cancel_order", arguments)

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_INVALID
    assert transport.requests == []
    assert store_app.state.store.orders["O000014"].status == "paid"


async def test_token_valido_executa_e_altera_o_pedido(
    make_executor, tokens: InMemoryTokenStore, store_app, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})

    result = await executor.invoke("Pedidos", "cancel_order", _cancel_args(token, "idem-ok-000001"))

    assert isinstance(result, CancelOrderOutput)
    assert result.status == "cancelled"
    assert len(transport.requests) == 1
    assert store_app.state.store.orders["O000014"].status == "cancelled"


async def test_token_reutilizado_e_recusado(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})
    await executor.invoke("Pedidos", "cancel_order", _cancel_args(token, "idem-uso-000001"))

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-uso-000002")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_INVALID
    assert len(transport.requests) == 1


async def test_token_de_outra_conversa_e_recusado_sem_consumir(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(
        tokens, "cancel_order", {"order_id": "O000014"}, conversation_id="conv-outra"
    )

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-conv-00001")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_INVALID
    assert transport.requests == []


async def test_token_de_outra_acao_e_recusado(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(tokens, "open_return", {"order_id": "O000014"})

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-acao-00001")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_INVALID
    assert transport.requests == []


async def test_token_de_outros_argumentos_e_recusado(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000015"})

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-args-00001", "O000014")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_INVALID
    assert transport.requests == []


async def test_mesma_chave_e_argumentos_reproduz_resultado_sem_novo_token(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport, store_app
):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})
    arguments = _cancel_args(token, "idem-replay-0001")
    first = await executor.invoke("Pedidos", "cancel_order", arguments)

    # Retry com o mesmo token já consumido: a chave devolve o resultado guardado antes da checagem.
    second = await executor.invoke("Pedidos", "cancel_order", arguments)

    assert second == first
    assert len(transport.requests) == 1
    assert store_app.state.store.orders["O000014"].status == "cancelled"


async def test_mesma_chave_com_argumentos_diferentes_e_conflito(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})
    await executor.invoke("Pedidos", "cancel_order", _cancel_args(token, "idem-conf-00001"))
    other_token = await issue_token(tokens, "cancel_order", {"order_id": "O000015"})

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(other_token, "idem-conf-00001", "O000015")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.IDEMPOTENCY_CONFLICT
    assert len(transport.requests) == 1


async def test_chave_reutilizada_na_loja_vira_idempotency_conflict(
    store_app, make_executor, tokens: InMemoryTokenStore
):
    first_client = httpx.AsyncClient(
        transport=RecordingTransport(httpx.ASGITransport(app=store_app)), base_url=STORE_URL
    )
    first_executor = make_executor(client=first_client)
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})
    await first_executor.invoke("Pedidos", "cancel_order", _cancel_args(token, "idem-loja-00001"))

    # Registro de idempotência vazio: a colisão precisa ser detectada pela própria loja (422).
    second_client = httpx.AsyncClient(
        transport=RecordingTransport(httpx.ASGITransport(app=store_app)), base_url=STORE_URL
    )
    second_executor = make_executor(client=second_client, idempotency=InMemoryIdempotencyRegistry())
    other_token = await issue_token(tokens, "cancel_order", {"order_id": "O000015"})

    result = await second_executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(other_token, "idem-loja-00001", "O000015")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.IDEMPOTENCY_CONFLICT


async def test_pedido_nao_cancelavel_consome_token_e_guarda_resultado(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000026"})
    arguments = _cancel_args(token, "idem-nao-canc-01", "O000026")

    first = await executor.invoke("Pedidos", "cancel_order", arguments)
    replay = await executor.invoke("Pedidos", "cancel_order", arguments)
    other_key = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-nao-canc-02", "O000026")
    )

    assert isinstance(first, ToolError)
    assert first.code is ToolErrorCode.NOT_CANCELABLE
    assert replay == first
    assert isinstance(other_key, ToolError)
    assert other_key.code is ToolErrorCode.CONFIRMATION_INVALID
    assert len(transport.requests) == 1


async def test_cancel_pedido_inexistente_vira_not_found(make_executor, tokens: InMemoryTokenStore):
    executor = make_executor()
    token = await issue_token(tokens, "cancel_order", {"order_id": "O999999"})

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-404-000001", "O999999")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND


async def test_open_return_executa_com_token_valido(
    make_executor, tokens: InMemoryTokenStore, store_app
):
    executor = make_executor()
    token = await issue_token(
        tokens,
        "open_return",
        {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": "tamanho errado"},
    )

    result = await executor.invoke(
        "PosVenda", "open_return", _return_args(token, "idem-ret-000001")
    )

    assert isinstance(result, OpenReturnOutput)
    assert result.status == "return_requested"
    assert store_app.state.store.orders["O000001"].status == "return_requested"


async def test_open_return_motivo_faz_parte_do_digest(
    make_executor, tokens: InMemoryTokenStore, transport: RecordingTransport
):
    executor = make_executor()
    token = await issue_token(
        tokens, "open_return", {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": "A"}
    )

    result = await executor.invoke(
        "PosVenda", "open_return", _return_args(token, "idem-mot-000001", "B")
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.CONFIRMATION_INVALID
    assert transport.requests == []


async def test_open_return_sku_fora_do_pedido_vira_not_found(
    make_executor, tokens: InMemoryTokenStore
):
    executor = make_executor()
    arguments = irreversible_arguments(
        "open_return", "t", "idem-sku-000001", order_id="O000001", sku="P0056-45-MARROM", reason="x"
    )
    token = await issue_token(tokens, "open_return", arguments)

    result = await executor.invoke(
        "PosVenda", "open_return", {**arguments, "confirmation_token": token}
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_FOUND


async def test_open_return_ja_solicitado_vira_already_requested(
    make_executor, tokens: InMemoryTokenStore
):
    executor = make_executor()
    arguments = irreversible_arguments(
        "open_return", "t", "idem-dup-000001", order_id="O000049", sku="P0126-G-MARROM", reason="x"
    )
    token = await issue_token(tokens, "open_return", arguments)

    result = await executor.invoke(
        "PosVenda", "open_return", {**arguments, "confirmation_token": token}
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.ALREADY_REQUESTED


async def test_open_return_fora_do_prazo_vira_not_eligible(
    make_executor, tokens: InMemoryTokenStore
):
    executor = make_executor()
    arguments = irreversible_arguments(
        "open_return",
        "t",
        "idem-prazo-00001",
        order_id="O000004",
        sku="P0056-45-MARROM",
        reason="x",
    )
    token = await issue_token(tokens, "open_return", arguments)

    result = await executor.invoke(
        "PosVenda", "open_return", {**arguments, "confirmation_token": token}
    )

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.NOT_ELIGIBLE


async def test_auditoria_uma_vez_com_irreversivel_e_sem_segredos(
    make_executor, tokens: InMemoryTokenStore
):
    events: list[ToolInvoked] = []

    async def audit(event: ToolInvoked) -> None:
        events.append(event)

    executor = make_executor(audit=audit)
    token = await issue_token(tokens, "cancel_order", {"order_id": "O000014"})

    result = await executor.invoke(
        "Pedidos", "cancel_order", _cancel_args(token, "idem-aud-000001")
    )

    assert isinstance(result, CancelOrderOutput)
    assert len(events) == 1
    event = events[0]
    assert event.tool_name == "cancel_order"
    assert event.agent == "Pedidos"
    assert event.irreversible is True
    assert event.succeeded is True
    assert event.latency_ms >= 0
    assert "confirmation_token" not in event.arguments
    assert token not in repr(event)
    assert action_digest("cancel_order", {"order_id": "O000014"}) not in repr(event)
