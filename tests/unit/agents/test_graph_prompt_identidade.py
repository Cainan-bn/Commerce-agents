"""Prompt do especialista informa o cliente identificado (H1, docs/evals/hipoteses-de-prompt.md)."""

import re

import pytest

from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.scripted_llm import ScriptedLLM
from tests.unit.agents.test_graph import Harness, _final

pytestmark = pytest.mark.unit

REGRA = "não peça o que as ferramentas devolvem"


async def _system(intent: str, customer: str) -> str:
    llm = ScriptedLLM([_final("Certo.")])
    harness = Harness(llm, FakeRouter(intent), StoreStub({"O000001": "C1234"}))

    await harness.turn("mensagem do cliente", customer=customer)

    return llm.calls[0][0].content


def _linha_com(texto: str, system: str) -> str:
    return next((linha for linha in system.splitlines() if texto in linha), "")


async def test_cliente_identificado_aparece_no_system_prompt_fora_de_dados():
    system = await _system("order_status", "C1234")

    linha = _linha_com("Cliente identificado: C1234", system)

    assert linha
    assert "<dados" not in linha


async def test_conversa_anonima_nao_informa_cliente_nem_id_algum():
    system = await _system("product_search", "")

    assert "Cliente identificado" not in system
    assert re.search(r"C\d{4}", system) is None


@pytest.mark.parametrize("intent", ["order_status", "return_eligibility"])
async def test_pedidos_e_pos_venda_recebem_regra_com_as_ferramentas_citadas(intent: str):
    system = await _system(intent, "C1234")

    regra = _linha_com(REGRA, system)

    assert regra
    assert "list_customer_orders" in regra
    assert "get_order_status" in regra


@pytest.mark.parametrize("intent", ["product_search", "policy_question"])
async def test_catalogo_e_politicas_nao_recebem_a_regra(intent: str):
    system = await _system(intent, "C1234")

    assert REGRA not in system


async def test_regra_nao_aparece_para_cliente_anonimo():
    system = await _system("product_search", "")

    assert REGRA not in system
