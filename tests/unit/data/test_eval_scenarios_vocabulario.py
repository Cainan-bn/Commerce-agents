"""Cenários só aceitam intenção, agente e ferramenta que o sistema tem.

Fontes da verdade (todas em `application`, que `data/` pode importar):
- intenções: `Intent` (application/dto/agents.py);
- agentes: valores de `AGENT_FOR_INTENT` (application/agents/turn.py);
- ferramentas e argumentos: `TOOL_SPECS` e `INPUT_MODELS` (application/dto/tools.py).
"""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from data.eval_scenarios_schema import TOOLS, EvalScenario
from pydantic import ValidationError

from commerce_agents.application.agents.turn import AGENT_FOR_INTENT
from commerce_agents.application.dto.agents import Intent
from commerce_agents.application.dto.tools import INPUT_MODELS, TOOL_SPECS

pytestmark = pytest.mark.unit

SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "data" / "eval_scenarios"
AGENTS = sorted(set(AGENT_FOR_INTENT.values()))

BASE: dict[str, Any] = {
    "id": "VOC-001",
    "split": "dev",
    "category": "pedidos",
    "persona": "cliente",
    "goal": "saber do pedido",
    "fixtures": {},
    "turns": ["mensagem"],
    "expected": {
        "intent": "order_status",
        "agent": "pedidos",
        "tools": [{"name": "get_order_status", "args": {"order_id": "O000001"}}],
        "forbidden_tools": ["cancel_order"],
        "irreversible_without_confirmation": False,
        "must_mention": [],
        "outcome": "resolved",
    },
}


def _with(**expected: Any) -> dict[str, Any]:
    raw = copy.deepcopy(BASE)
    raw["expected"].update(expected)
    return raw


def _load(raw: dict[str, Any]) -> EvalScenario:
    return EvalScenario.model_validate(raw, strict=True)


def test_cenario_base_e_valido():
    assert _load(BASE).expected.intent == "order_status"


# ----------------------------------------------------------------------------- intenção


@pytest.mark.parametrize("intent", list(Intent), ids=[i.value for i in Intent])
def test_toda_intencao_do_sistema_e_aceita(intent: Intent):
    assert _load(_with(intent=intent.value)).expected.intent == intent.value


def test_intencao_fora_de_intent_e_recusada_citando_o_valor_e_os_validos():
    with pytest.raises(ValidationError) as invalid:
        _load(_with(intent="consulta_pedido"))

    message = str(invalid.value)
    assert "consulta_pedido" in message
    for intent in Intent:
        assert intent.value in message


# ------------------------------------------------------------------------------- agente


@pytest.mark.parametrize("agent", AGENTS)
def test_todo_agente_do_roteamento_e_aceito(agent: str):
    assert _load(_with(agent=agent)).expected.agent == agent


@pytest.mark.parametrize("agent", ["atendimento", "Pedidos", "PosVenda", "suporte"])
def test_agente_fora_do_roteamento_e_recusado_citando_o_valor(agent: str):
    with pytest.raises(ValidationError) as invalid:
        _load(_with(agent=agent))

    assert agent in str(invalid.value)


# --------------------------------------------------------------------------- ferramentas


def test_vocabulario_de_ferramentas_do_schema_e_o_catalogo_do_sistema():
    assert set(TOOLS) == set(TOOL_SPECS)


def test_ferramenta_esperada_fora_do_catalogo_e_recusada():
    with pytest.raises(ValidationError) as invalid:
        _load(_with(tools=[{"name": "track_package", "args": {}}]))

    assert "track_package" in str(invalid.value)


def test_ferramenta_proibida_fora_do_catalogo_e_recusada():
    with pytest.raises(ValidationError) as invalid:
        _load(_with(forbidden_tools=["delete_order"]))

    assert "delete_order" in str(invalid.value)


def test_argumento_inexistente_no_schema_de_entrada_e_recusado():
    assert "product_id" not in INPUT_MODELS["quote_shipping"].model_fields

    with pytest.raises(ValidationError) as invalid:
        _load(
            _with(
                tools=[
                    {
                        "name": "quote_shipping",
                        "args": {"product_id": "P0001", "cep": "01000-000"},
                    }
                ]
            )
        )

    message = str(invalid.value)
    assert "product_id" in message
    assert "quote_shipping" in message


def test_argumentos_parciais_do_schema_de_entrada_sao_aceitos():
    campo = next(iter(INPUT_MODELS["search_policies"].model_fields))

    scenario = _load(_with(tools=[{"name": "search_policies", "args": {campo: "troca"}}]))

    assert scenario.expected.tools[0].args == {campo: "troca"}


# -------------------------------------------------------------------------------- guarda


def test_os_54_cenarios_do_dev_continuam_validos():
    paths = sorted(SCENARIOS_DIR.glob("*.yaml"))

    loaded = [_load(yaml.safe_load(path.read_text(encoding="utf-8"))) for path in paths]

    assert len(loaded) == 54
