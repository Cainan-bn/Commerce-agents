"""preflight_irreversible: respostas inesperadas da loja e ferramentas sem pré-checagem."""

from typing import Any

import pytest

from commerce_agents.application.agents.preflight import preflight_irreversible
from commerce_agents.application.dto.tools import SearchPoliciesOutput, ToolErrorCode

pytestmark = pytest.mark.unit


class _Inner:
    async def invoke(self, agent: str, tool_name: str, arguments: Any, **kwargs: Any) -> Any:
        return SearchPoliciesOutput(chunks=())


@pytest.mark.parametrize("tool", ["cancel_order", "open_return"])
async def test_resposta_inesperada_vira_upstream_error(tool: str):
    result = await preflight_irreversible(
        _Inner(),
        "Pedidos",
        tool,
        {"order_id": "O000001", "sku": "P0001-M-AZUL"},
        conversation_id="c",
    )

    assert result is not None
    assert result.code is ToolErrorCode.UPSTREAM_ERROR


async def test_ferramenta_sem_regra_passa():
    assert (
        await preflight_irreversible(_Inner(), "Pedidos", "outra", {}, conversation_id="c") is None
    )


# ------------------------------------------------- H4: orientar devolução no pedido já enviado

TRACKING = "TH100000001BR"


class _Orders:
    """Loja que devolve um pedido com o status e o rastreio dados (via `get_order_status`)."""

    def __init__(self, status: str, tracking_code: str | None = TRACKING) -> None:
        self._status = status
        self._tracking_code = tracking_code

    async def invoke(self, agent: str, tool_name: str, arguments: Any, **kwargs: Any) -> Any:
        from datetime import UTC, datetime

        from commerce_agents.application.dto.tools import GetOrderStatusOutput
        from commerce_agents.application.dto.views import OrderView

        return GetOrderStatusOutput(
            order=OrderView(
                order_id="O000017",
                customer_id="C1234",
                status=self._status,
                tracking_code=self._tracking_code,
                created_at=datetime(2026, 11, 1, tzinfo=UTC),
                delivered_at=None,
                total_cents=1000,
            )
        )


async def _cancel(status: str, tracking_code: str | None = TRACKING):  # type: ignore[no-untyped-def]
    return await preflight_irreversible(
        _Orders(status, tracking_code),
        "Pedidos",
        "cancel_order",
        {"order_id": "O000017"},
        conversation_id="c",
    )


@pytest.mark.parametrize("status", ["shipped", "in_transit", "delivered"])
async def test_cancelar_pedido_enviado_ou_entregue_orienta_devolucao(status: str):
    error = await _cancel(status)

    assert error is not None
    assert error.code is ToolErrorCode.NOT_CANCELABLE
    assert "não pode mais ser cancelado" in error.message
    assert "devolução" in error.message


async def test_cancelar_pedido_enviado_informa_o_rastreio_quando_existe():
    error = await _cancel("shipped", TRACKING)

    assert error is not None
    assert TRACKING in error.message


@pytest.mark.parametrize("status", ["shipped", "delivered"])
async def test_cancelar_pedido_sem_rastreio_nao_cita_rastreio_vazio(status: str):
    error = await _cancel(status, None)

    assert error is not None
    assert "devolução" in error.message
    assert "None" not in error.message


async def test_cancelar_pedido_ja_cancelado_nao_orienta_devolucao():
    error = await _cancel("cancelled")

    assert error is not None
    assert error.code is ToolErrorCode.NOT_CANCELABLE
    assert "devolução" not in error.message


async def test_cancelar_pedido_aguardando_pagamento_segue_sem_erro_e_sem_orientacao():
    assert await _cancel("pending_payment") is None


@pytest.mark.parametrize("status", ["shipped", "in_transit", "delivered"])
async def test_orientacao_de_devolucao_nao_traz_token_nem_segredo(status: str):
    error = await _cancel(status)

    assert error is not None
    texto = error.message.lower()
    assert "token" not in texto
    assert "idempot" not in texto
    assert "chave" not in texto
