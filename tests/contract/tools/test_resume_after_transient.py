"""Retomada após erro transitório com token já consumido (ADR 0011, decisão do Líder).

Quando o token foi consumido e as tentativas se esgotam por erro transitório, o executor grava
um marcador PENDENTE na idempotência. Um novo invoke com a mesma chave, mesmos argumentos e
token consumido (ou ausente do store) não consome token, repete a chamada com a mesma
Idempotency-Key e conclui a ação uma única vez na loja.
"""

import json

import httpx
import pytest

from commerce_agents.application.dto.tools import (
    OUTPUT_MODELS,
    ToolError,
    ToolErrorCode,
    action_digest,
)
from tests.fakes.confirmation import PENDING_RESULT, InMemoryTokenStore
from tests.fakes.http import RecordingTransport
from tests.fakes.tools import STORE_URL, irreversible_arguments, issue_token

pytestmark = pytest.mark.contract

KEY = "idem-resume-0001"

# (ferramenta, agente, campos de ação, campos de ação alternativos com outro digest)
CASES = [
    pytest.param(
        "cancel_order",
        "Pedidos",
        {"order_id": "O000014"},
        {"order_id": "O000015"},
        id="cancel_order",
    ),
    pytest.param(
        "open_return",
        "PosVenda",
        {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": "tamanho errado"},
        {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": "outro motivo"},
        id="open_return",
    ),
]

# Pedido afetado por cada ferramenta na loja, para checar a alteração única.
STORE_ORDER_AFTER = {
    "cancel_order": ("O000014", "cancelled"),
    "open_return": ("O000001", "return_requested"),
}


def _args(tool: str, key: str, token: str, action: dict[str, str]) -> dict[str, object]:
    return irreversible_arguments(tool, token, key, **action)


def _failing_transport(store_app, fail_first: int) -> tuple[RecordingTransport, httpx.AsyncClient]:
    transport = RecordingTransport(
        httpx.ASGITransport(app=store_app), fail_first=fail_first, fail_status=503
    )
    return transport, httpx.AsyncClient(transport=transport, base_url=STORE_URL)


@pytest.mark.parametrize(("tool", "agent", "action", "other_action"), CASES)
async def test_erro_transitorio_esgotado_grava_pendente(
    store_app,
    make_executor,
    tokens: InMemoryTokenStore,
    idempotency,
    tool,
    agent,
    action,
    other_action,
):
    # max_retries=1 nas irreversíveis: N = retries + 1 = 2 tentativas, todas falhando.
    transport, client = _failing_transport(store_app, fail_first=2)
    executor = make_executor(client=client)
    token = await issue_token(tokens, tool, action)

    result = await executor.invoke(agent, tool, _args(tool, KEY, token, action))

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True
    assert len(transport.requests) == 2
    assert await idempotency.get(KEY) == (action_digest(tool, action), PENDING_RESULT)


@pytest.mark.parametrize("token_state", ["consumido", "ausente"])
@pytest.mark.parametrize(("tool", "agent", "action", "other_action"), CASES)
async def test_retomada_com_mesma_chave_conclui_uma_unica_vez(
    store_app,
    make_executor,
    tokens: InMemoryTokenStore,
    idempotency,
    tool,
    agent,
    action,
    other_action,
    token_state,
):
    transport, client = _failing_transport(store_app, fail_first=2)
    executor = make_executor(client=client)
    token = await issue_token(tokens, tool, action)
    first = await executor.invoke(agent, tool, _args(tool, KEY, token, action))
    assert isinstance(first, ToolError) and first.retryable is True

    retry_tokens = tokens if token_state == "consumido" else InMemoryTokenStore()
    retry_executor = make_executor(client=client, tokens=retry_tokens)
    resumed = await retry_executor.invoke(agent, tool, _args(tool, KEY, token, action))

    output_model = OUTPUT_MODELS[tool]
    assert isinstance(resumed, output_model)
    assert resumed.ok is True
    assert len(transport.requests) == 3  # 2 falhas + 1 sucesso, nenhuma tentativa extra
    assert {request.headers["Idempotency-Key"] for request in transport.requests} == {KEY}
    order_id, status = STORE_ORDER_AFTER[tool]
    assert store_app.state.store.orders[order_id].status == status
    stored = await idempotency.get(KEY)
    assert stored is not None
    assert stored[0] == action_digest(tool, action)
    assert stored[1] != PENDING_RESULT
    assert json.loads(stored[1])["ok"] is True


@pytest.mark.parametrize(("tool", "agent", "action", "other_action"), CASES)
async def test_mesma_chave_com_argumentos_diferentes_continua_conflito(
    store_app,
    make_executor,
    tokens: InMemoryTokenStore,
    idempotency,
    tool,
    agent,
    action,
    other_action,
):
    transport, client = _failing_transport(store_app, fail_first=2)
    executor = make_executor(client=client)
    token = await issue_token(tokens, tool, action)
    await executor.invoke(agent, tool, _args(tool, KEY, token, action))
    other_token = await issue_token(tokens, tool, other_action)

    result = await executor.invoke(agent, tool, _args(tool, KEY, other_token, other_action))

    assert isinstance(result, ToolError)
    assert result.code is ToolErrorCode.IDEMPOTENCY_CONFLICT
    assert len(transport.requests) == 2
    assert await idempotency.get(KEY) == (action_digest(tool, action), PENDING_RESULT)


@pytest.mark.parametrize(("tool", "agent", "action", "other_action"), CASES)
async def test_pendente_nunca_e_devolvido_como_resultado(
    store_app,
    make_executor,
    tokens: InMemoryTokenStore,
    idempotency,
    tool,
    agent,
    action,
    other_action,
):
    # Falhas continuam nas duas rodadas: a retomada também se esgota e continua pendente.
    transport, client = _failing_transport(store_app, fail_first=4)
    executor = make_executor(client=client)
    token = await issue_token(tokens, tool, action)
    await executor.invoke(agent, tool, _args(tool, KEY, token, action))

    retried = await executor.invoke(agent, tool, _args(tool, KEY, token, action))

    assert isinstance(retried, ToolError)
    assert retried.code is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert retried.retryable is True
    assert PENDING_RESULT not in retried.message
    assert await idempotency.get(KEY) == (action_digest(tool, action), PENDING_RESULT)
