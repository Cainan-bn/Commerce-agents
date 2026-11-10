"""Custo estimado por token (ADR 0015). Modelo ausente da tabela vira `None`, nunca um chute.

Usado pelos providers em produção para preencher `LLMResult.cost_usd` (Fase 09).
"""

from collections.abc import Mapping
from pathlib import Path

import yaml

PRICING_FILE = Path(__file__).with_name("pricing.yaml")

PriceTable = Mapping[str, Mapping[str, float]]


def load_pricing(path: Path = PRICING_FILE) -> dict[str, dict[str, float]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = data.get("models") or {}
    return {str(model): dict(prices) for model, prices in models.items()}


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int, table: PriceTable
) -> float | None:
    prices = table.get(model)
    if prices is None:
        return None
    return (
        input_tokens * prices["input_per_million_usd"]
        + output_tokens * prices["output_per_million_usd"]
    ) / 1_000_000
