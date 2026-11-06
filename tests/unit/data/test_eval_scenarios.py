"""Validação do golden set de cenários de avaliação (split dev)."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from data.eval_scenarios_schema import TOOLS, EvalScenario

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS_DIR = REPO_ROOT / "data" / "eval_scenarios"
SEED_DIR = REPO_ROOT / "data" / "seed"

EXPECTED_COUNTS: dict[str, int] = {
    "pedidos": 14,
    "catalogo": 7,
    "politicas": 8,
    "pos_venda": 8,
    "injection": 6,
    "ambiguo": 8,
    "handoff": 3,
}


def _load_jsonl(name: str) -> list[dict[str, Any]]:
    path = SEED_DIR / name
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture(scope="module")
def scenarios() -> list[EvalScenario]:
    loaded: list[EvalScenario] = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        loaded.append(EvalScenario.model_validate(raw, strict=True))
    return loaded


@pytest.fixture(scope="module")
def seed_index() -> dict[str, Any]:
    customers = _load_jsonl("customers.jsonl")
    orders = _load_jsonl("orders.jsonl")
    products = _load_jsonl("products.jsonl")
    return {
        "customer_ids": {c["customer_id"] for c in customers},
        "order_owner": {o["order_id"]: o["customer_id"] for o in orders},
        "skus": {variant["sku"] for product in products for variant in product["variants"]},
        "product_ids": {product["product_id"] for product in products},
    }


@pytest.mark.unit
def test_scenario_counts_and_split(scenarios: list[EvalScenario]) -> None:
    by_category = Counter(scenario.category for scenario in scenarios)

    assert len(scenarios) == 54
    assert all(scenario.split == "dev" for scenario in scenarios)
    assert dict(by_category) == EXPECTED_COUNTS
    assert by_category["injection"] >= 6
    assert by_category["ambiguo"] >= 8


@pytest.mark.unit
def test_scenario_ids_are_unique(scenarios: list[EvalScenario]) -> None:
    ids = [scenario.id for scenario in scenarios]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_tool_names_within_vocabulary(scenarios: list[EvalScenario]) -> None:
    for scenario in scenarios:
        for tool in scenario.expected.tools:
            assert tool.name in TOOLS, f"{scenario.id}: ferramenta desconhecida {tool.name}"
        for name in scenario.expected.forbidden_tools:
            assert name in TOOLS, f"{scenario.id}: ferramenta desconhecida {name}"


@pytest.mark.unit
def test_fixtures_exist_in_seed(scenarios: list[EvalScenario], seed_index: dict[str, Any]) -> None:
    for scenario in scenarios:
        fixtures = scenario.fixtures
        if "customer_id" in fixtures:
            assert fixtures["customer_id"] in seed_index["customer_ids"], scenario.id
        if "order_id" in fixtures:
            assert fixtures["order_id"] in seed_index["order_owner"], scenario.id
            if "customer_id" in fixtures:
                assert (
                    seed_index["order_owner"][fixtures["order_id"]] == fixtures["customer_id"]
                ), f"{scenario.id}: pedido {fixtures['order_id']} não pertence ao cliente"
        if "sku" in fixtures:
            assert fixtures["sku"] in seed_index["skus"], scenario.id
        if "product_id" in fixtures:
            assert fixtures["product_id"] in seed_index["product_ids"], scenario.id


@pytest.mark.unit
def test_irreversible_always_requires_confirmation(scenarios: list[EvalScenario]) -> None:
    for scenario in scenarios:
        assert scenario.expected.irreversible_without_confirmation is False, scenario.id


@pytest.mark.unit
def test_injection_scenarios_are_refused(scenarios: list[EvalScenario]) -> None:
    for scenario in scenarios:
        if scenario.category != "injection":
            continue
        assert scenario.expected.outcome == "refused", scenario.id
        assert scenario.expected.leaks == "forbidden", scenario.id
        assert scenario.expected.forbidden_tools, scenario.id


@pytest.mark.unit
def test_ambiguo_scenarios_are_clarified(scenarios: list[EvalScenario]) -> None:
    for scenario in scenarios:
        if scenario.category == "ambiguo":
            assert scenario.expected.outcome == "clarified", scenario.id


@pytest.mark.unit
def test_handoff_scenarios_request_handoff(scenarios: list[EvalScenario]) -> None:
    for scenario in scenarios:
        if scenario.category != "handoff":
            continue
        assert scenario.expected.outcome == "handoff", scenario.id
        assert any(tool.name == "request_handoff" for tool in scenario.expected.tools), scenario.id
