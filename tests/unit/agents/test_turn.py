"""Mapas fixos do turno (ADR 0013) conferidos contra os cenários de avaliação dev."""

from pathlib import Path

import pytest
import yaml

from commerce_agents.application.dto.agents import Intent
from commerce_agents.application.dto.tools import AGENT_ALLOWLIST

pytestmark = pytest.mark.unit

SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "data" / "eval_scenarios"


def _turn():  # type: ignore[no-untyped-def]
    from commerce_agents.application.agents import turn

    return turn


def _dev_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data.get("split") == "dev":
            scenarios.append(data)
    return scenarios


def test_agent_for_intent_cobre_todos_os_intents():
    mapping = _turn().AGENT_FOR_INTENT

    assert set(mapping) == set(Intent)


def test_agent_for_intent_bate_com_os_cenarios_dev():
    mapping = _turn().AGENT_FOR_INTENT
    scenarios = _dev_scenarios()
    assert len(scenarios) == 54

    mismatches = {
        scenario["id"]
        for scenario in scenarios
        if mapping[Intent(scenario["expected"]["intent"])] != scenario["expected"]["agent"]
    }

    assert mismatches == set()


def test_agent_tool_key_e_consistente_com_a_allowlist():
    turn = _turn()

    assert set(turn.AGENT_TOOL_KEY.values()) <= set(AGENT_ALLOWLIST)
    assert turn.AGENT_TOOL_KEY == {
        "pedidos": "Pedidos",
        "catalogo": "CatalogoVendas",
        "politicas": "Politicas",
        "pos_venda": "PosVenda",
    }


def test_limites_do_turno():
    turn = _turn()

    assert turn.MAX_TOOL_STEPS == 4
    assert turn.MIN_CONFIDENCE == 0.5


@pytest.mark.parametrize(
    "agent_key",
    ["pedidos", "catalogo", "politicas", "pos_venda"],
)
def test_agentes_especialistas_tem_chave_de_ferramenta(agent_key: str):
    assert agent_key in _turn().AGENT_TOOL_KEY
