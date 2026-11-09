"""Prompt do catalogo: obter SKU de variante antes de cotar frete (H3, hipoteses-de-prompt.md).

O catálogo de ferramentas já cita `quote_shipping` e `check_availability`; por isso a regra é
procurada na linha que contém a frase-âncora, não em qualquer lugar do prompt.
"""

from pathlib import Path

import pytest
import yaml

from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.scripted_llm import ScriptedLLM
from tests.unit.agents.test_graph import Harness, _final

pytestmark = pytest.mark.unit

SCENARIOS = Path(__file__).resolve().parents[3] / "data" / "eval_scenarios"
ANCORA = "o frete não depende de tamanho nem cor"


async def _system(intent: str, customer: str) -> str:
    llm = ScriptedLLM([_final("Certo.")])
    harness = Harness(llm, FakeRouter(intent), StoreStub({"O000001": "C1234"}))

    await harness.turn("mensagem do cliente", customer=customer)

    return llm.calls[0][0].content


def _linha_com(texto: str, system: str) -> str:
    return next((linha for linha in system.splitlines() if texto in linha), "")


@pytest.mark.parametrize("customer", ["", "C1234"], ids=["anonimo", "identificado"])
async def test_catalogo_recebe_a_regra_de_frete_com_as_ferramentas(customer: str):
    regra = _linha_com(ANCORA, await _system("shipping_quote", customer))

    assert regra
    assert "quote_shipping" in regra
    assert "check_availability" in regra


async def test_regra_manda_obter_sku_de_variante_antes_de_cotar():
    regra = _linha_com(ANCORA, await _system("shipping_quote", ""))

    assert "SKU" in regra
    assert "variante" in regra
    assert "antes de" in regra


@pytest.mark.parametrize(
    "intent",
    ["order_status", "return_eligibility", "policy_question"],
    ids=["pedidos", "pos_venda", "politicas"],
)
async def test_regra_de_frete_nao_aparece_fora_do_catalogo(intent: str):
    assert ANCORA not in await _system(intent, "C1234")


async def test_prompt_do_catalogo_nao_copia_dados_nem_frases_dos_cenarios():
    system = await _system("shipping_quote", "")
    turnos = [
        turno
        for path in sorted(SCENARIOS.glob("*.yaml"))
        for turno in yaml.safe_load(path.read_text(encoding="utf-8"))["turns"]
    ]

    assert "P0001" not in system
    assert "01000-000" not in system
    assert turnos
    assert [t for t in turnos if t.lower() in system.lower()] == []
