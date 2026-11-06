"""ProposeIrreversibleAction: só irreversíveis, só action_fields, token vinculado ao digest."""

import unicodedata
from datetime import timedelta
from typing import Any

import pytest

from commerce_agents.application.dto.tools import action_digest
from tests.fakes.clock import FakeClock
from tests.fakes.confirmation import InMemoryTokenStore
from tests.fakes.tools import CONVERSATION_ID, FAKE_CANCEL_ORDER_ARGS

pytestmark = pytest.mark.unit


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


async def test_proposta_guarda_somente_action_fields(make_propose: Any):
    propose = make_propose()
    arguments = {**FAKE_CANCEL_ORDER_ARGS, "idempotency_key": "nao-deve-entrar", "lixo": "x"}

    pending = await propose.execute(CONVERSATION_ID, "Pedidos", "cancel_order", arguments)

    assert dict(pending.arguments) == {"order_id": "O000014"}


async def test_summary_menciona_pedido_e_avisa_irreversibilidade(make_propose: Any):
    propose = make_propose()

    pending = await propose.execute(
        CONVERSATION_ID, "Pedidos", "cancel_order", {"order_id": "O000014"}
    )

    summary = _norm(pending.summary)
    assert "O000014".lower() in summary
    assert "pedido" in summary
    assert "nao pode ser desfeita" in summary


async def test_summary_de_devolucao_menciona_pedido_sku_e_motivo(make_propose: Any):
    propose = make_propose()

    pending = await propose.execute(
        CONVERSATION_ID,
        "PosVenda",
        "open_return",
        {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": "tamanho errado"},
    )

    summary = _norm(pending.summary)
    assert "o000001" in summary
    assert "p0168-gg-azul" in summary
    assert "tamanho errado" in summary
    assert "nao pode ser desfeita" in summary


async def test_expira_em_clock_mais_ttl(make_propose: Any, clock: FakeClock):
    propose = make_propose(ttl_seconds=120)

    pending = await propose.execute(
        CONVERSATION_ID, "Pedidos", "cancel_order", {"order_id": "O000014"}
    )

    assert pending.expires_at == clock() + timedelta(seconds=120)


async def test_chave_de_idempotencia_vem_de_new_key(make_propose: Any):
    propose = make_propose(new_key=lambda: "idem-gerada-42")

    pending = await propose.execute(
        CONVERSATION_ID, "Pedidos", "cancel_order", {"order_id": "O000014"}
    )

    assert pending.idempotency_key == "idem-gerada-42"


async def test_token_fica_vinculado_ao_digest_dos_argumentos(
    make_propose: Any, tokens: InMemoryTokenStore
):
    propose = make_propose()
    pending = await propose.execute(
        CONVERSATION_ID, "Pedidos", "cancel_order", {"order_id": "O000014"}
    )

    wrong = await tokens.consume(
        pending.confirmation_token,
        CONVERSATION_ID,
        "cancel_order",
        action_digest("cancel_order", {"order_id": "O000015"}),
    )
    right = await tokens.consume(
        pending.confirmation_token,
        CONVERSATION_ID,
        "cancel_order",
        action_digest("cancel_order", {"order_id": "O000014"}),
    )

    assert wrong is False
    assert right is True


@pytest.mark.parametrize(
    ("agent", "tool_name", "arguments"),
    [
        ("CatalogoVendas", "search_products", {"query": "tênis"}),
        ("Pedidos", "get_order_status", {"order_id": "O000014"}),
        ("Politicas", "search_policies", {"query": "prazo"}),
    ],
)
async def test_ferramenta_nao_irreversivel_vira_value_error(
    make_propose: Any, agent: str, tool_name: str, arguments: dict[str, Any]
):
    propose = make_propose()

    with pytest.raises(ValueError):
        await propose.execute(CONVERSATION_ID, agent, tool_name, arguments)


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("cancel_order", {"order_id": "O1"}),
        ("cancel_order", {}),
        ("open_return", {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": ""}),
        ("open_return", {"order_id": "O000001", "sku": "X", "reason": "motivo"}),
    ],
)
async def test_argumento_invalido_vira_value_error(
    make_propose: Any, tool_name: str, arguments: dict[str, Any]
):
    propose = make_propose()

    with pytest.raises(ValueError):
        await propose.execute(CONVERSATION_ID, "Pedidos", tool_name, arguments)
