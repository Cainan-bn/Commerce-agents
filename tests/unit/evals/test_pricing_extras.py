"""load_pricing: arquivo padrão sem preços inventados e leitura de tabela."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_arquivo_padrao_carrega_sem_modelos_inventados():
    from commerce_agents.infrastructure.llm.pricing import load_pricing

    assert load_pricing() == {}


def test_load_pricing_le_a_tabela(tmp_path: Path):
    from commerce_agents.infrastructure.llm.pricing import load_pricing

    path = tmp_path / "p.yaml"
    path.write_text(
        "models:\n  m:\n    input_per_million_usd: 1.0\n    output_per_million_usd: 2.0\n",
        encoding="utf-8",
    )

    assert load_pricing(path) == {
        "m": {"input_per_million_usd": 1.0, "output_per_million_usd": 2.0}
    }


def test_load_pricing_arquivo_vazio(tmp_path: Path):
    from commerce_agents.infrastructure.llm.pricing import load_pricing

    path = tmp_path / "p.yaml"
    path.write_text("", encoding="utf-8")

    assert load_pricing(path) == {}
