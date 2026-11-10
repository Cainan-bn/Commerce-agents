"""estimate_cost_usd (ADR 0015): preço por milhão de tokens; modelo ausente vira None."""

import pytest

pytestmark = pytest.mark.unit

TABLE = {
    "modelo-a": {"input_per_million_usd": 0.50, "output_per_million_usd": 1.50},
}


def _cost(model: str, input_tokens: int, output_tokens: int, table: dict) -> float | None:  # type: ignore[type-arg]
    from evals.pricing import estimate_cost_usd

    return estimate_cost_usd(model, input_tokens, output_tokens, table)


def test_custo_por_milhao_de_tokens():
    cost = _cost("modelo-a", 2_000_000, 1_000_000, TABLE)

    assert cost == pytest.approx(2 * 0.50 + 1 * 1.50)


def test_modelo_ausente_da_tabela_devolve_none():
    assert _cost("modelo-desconhecido", 1000, 1000, TABLE) is None


def test_zero_tokens_custa_zero():
    assert _cost("modelo-a", 0, 0, TABLE) == 0.0
