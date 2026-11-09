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


# ----------------------------------------------------------------- H1b: pos_venda deriva o SKU

REGRA_DEVOLUCAO = "não pergunte o item quando o pedido tiver um só item"


async def test_pos_venda_identificado_orienta_derivar_o_sku_do_pedido():
    system = await _system("return_eligibility", "C1234")

    regra = _linha_com(REGRA_DEVOLUCAO, system)

    assert regra
    assert "get_order_status" in regra
    assert "check_return_eligibility" in regra


async def test_pos_venda_identificado_nao_convida_a_perguntar_o_item():
    system = await _system("return_eligibility", "C1234")

    assert "qual item e o motivo" not in system


async def test_pedidos_identificado_mantem_leitura_e_nao_recebe_regra_de_devolucao():
    system = await _system("order_status", "C1234")

    regra = _linha_com(REGRA, system)

    assert "list_customer_orders" in regra
    assert "get_order_status" in regra
    assert REGRA_DEVOLUCAO not in system
    assert "check_return_eligibility" not in regra


@pytest.mark.parametrize(
    ("intent", "customer"),
    [("product_search", ""), ("product_search", "C1234"), ("policy_question", "C1234")],
    ids=["anonimo", "catalogo", "politicas"],
)
async def test_regra_de_devolucao_so_vai_para_pos_venda_identificado(intent: str, customer: str):
    system = await _system(intent, customer)

    assert REGRA_DEVOLUCAO not in system


# ------------------------------------- confie no eligible e não compare datas (pos_venda)

FRASE_ELIGIBLE = "confie no campo eligible"
FRASE_DATA = "você não sabe a data de hoje"


async def test_pos_venda_identificado_manda_confiar_em_eligible_e_nao_comparar_datas():
    system = await _system("return_eligibility", "C1234")

    regra = _linha_com(REGRA_DEVOLUCAO, system)

    assert FRASE_ELIGIBLE in regra
    assert FRASE_DATA in regra


@pytest.mark.parametrize(
    ("intent", "customer"),
    [
        ("order_status", "C1234"),
        ("product_search", ""),
        ("product_search", "C1234"),
        ("policy_question", "C1234"),
    ],
    ids=["pedidos", "anonimo", "catalogo", "politicas"],
)
async def test_frases_de_elegibilidade_e_data_so_vao_para_pos_venda_identificado(
    intent: str, customer: str
):
    system = await _system(intent, customer)

    assert FRASE_ELIGIBLE not in system
    assert FRASE_DATA not in system


# ------------------------------------------------ H4: repassar orientação vinda da ferramenta

FRASE_ORIENTACAO = "Se uma ferramenta devolver orientação ao cliente (ex.: devolução), repasse-a"


@pytest.mark.parametrize("intent", ["order_status", "return_eligibility"])
async def test_pedidos_e_pos_venda_repassam_orientacao_da_ferramenta(intent: str):
    system = await _system(intent, "C1234")

    assert FRASE_ORIENTACAO in system
