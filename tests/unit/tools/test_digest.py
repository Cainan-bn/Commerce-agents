"""Propriedades do digest de ação que vincula o token aos argumentos (ADR 0011)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.application.dto.tools import action_digest

pytestmark = pytest.mark.unit

ORDER_IDS = st.from_regex(r"O\d{6}", fullmatch=True)
SKUS = st.from_regex(r"[A-Z0-9-]{3,30}", fullmatch=True)
REASONS = st.text(min_size=1, max_size=100)
NON_ACTION_FIELDS = ("conversation_id", "confirmation_token", "idempotency_key", "ruido")
EXTRAS = st.dictionaries(
    st.sampled_from(NON_ACTION_FIELDS), st.text(max_size=40), max_size=len(NON_ACTION_FIELDS)
)


@given(order_id=ORDER_IDS, sku=SKUS, reason=REASONS, extra=EXTRAS)
def test_digest_ignora_campos_fora_de_action_fields(order_id, sku, reason, extra):
    base = {"order_id": order_id, "sku": sku, "reason": reason}

    assert action_digest("open_return", {**base, **extra}) == action_digest("open_return", base)


@given(order_id=ORDER_IDS, sku=SKUS, reason=REASONS)
def test_digest_e_estavel_independente_da_ordem_das_chaves(order_id, sku, reason):
    base = {"order_id": order_id, "sku": sku, "reason": reason}
    reordered = dict(reversed(list(base.items())))

    assert action_digest("open_return", base) == action_digest("open_return", reordered)
    assert action_digest("open_return", base) == action_digest("open_return", base)


@given(order_id=ORDER_IDS, other=ORDER_IDS)
def test_digest_muda_quando_order_id_muda(order_id, other):
    if order_id == other:
        return
    assert action_digest("cancel_order", {"order_id": order_id}) != action_digest(
        "cancel_order", {"order_id": other}
    )


@given(order_id=ORDER_IDS, sku=SKUS, reason=REASONS)
def test_digest_muda_quando_qualquer_campo_de_acao_muda(order_id, sku, reason):
    base = {"order_id": order_id, "sku": sku, "reason": reason}
    digest = action_digest("open_return", base)

    other_order = "O999999" if order_id != "O999999" else "O000001"
    assert digest != action_digest("open_return", {**base, "order_id": other_order})
    assert digest != action_digest("open_return", {**base, "sku": sku + "Z"})
    assert digest != action_digest("open_return", {**base, "reason": reason + "x"})


def test_digest_separa_ferramentas_com_mesmos_argumentos():
    arguments = {"order_id": "O000014"}

    assert action_digest("cancel_order", arguments) != action_digest(
        "open_return", {**arguments, "sku": "ABC", "reason": "r"}
    )
