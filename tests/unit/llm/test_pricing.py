"""estimate_cost_usd (ADR 0015): preço por milhão de tokens; modelo ausente vira None.

A tabela mora em `commerce_agents.infrastructure.llm.pricing` (Fase 09), usada em produção.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TABLE = {
    "modelo-a": {"input_per_million_usd": 0.50, "output_per_million_usd": 1.50},
}


def _cost(model: str, input_tokens: int, output_tokens: int, table: dict) -> float | None:  # type: ignore[type-arg]
    from commerce_agents.infrastructure.llm.pricing import estimate_cost_usd

    return estimate_cost_usd(model, input_tokens, output_tokens, table)


def test_custo_por_milhao_de_tokens():
    cost = _cost("modelo-a", 2_000_000, 1_000_000, TABLE)

    assert cost == pytest.approx(2 * 0.50 + 1 * 1.50)


def test_modelo_ausente_da_tabela_devolve_none():
    assert _cost("modelo-desconhecido", 1000, 1000, TABLE) is None


def test_zero_tokens_custa_zero():
    assert _cost("modelo-a", 0, 0, TABLE) == 0.0


def test_tabela_mora_ao_lado_do_modulo_em_src():
    from commerce_agents.infrastructure.llm import pricing

    assert pricing.PRICING_FILE.name == "pricing.yaml"
    assert pricing.PRICING_FILE.parent == Path(pricing.__file__).parent
    assert pricing.PRICING_FILE.is_file()


def test_evals_pricing_se_existir_reexporta_o_de_src():
    from commerce_agents.infrastructure.llm import pricing

    try:
        import evals.pricing as legacy
    except ModuleNotFoundError:
        return
    assert legacy.estimate_cost_usd is pricing.estimate_cost_usd
    assert legacy.load_pricing is pricing.load_pricing
