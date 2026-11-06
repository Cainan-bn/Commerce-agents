"""Pré-checagem antes de propor ação irreversível (decisão do Líder): posse e viabilidade em código.

Antes de ProposeIrreversibleAction o grafo lê o pedido pelo ScopedToolInvoker. Se a ação não é
viável (status, prazo, posse), devolve o ToolError ao LLM e NÃO emite token nem propõe.
"""

import pytest

from commerce_agents.application.dto.tools import (
    CheckReturnEligibilityOutput,
    ToolError,
    ToolErrorCode,
)
from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.clock import BASE_TIME
from tests.fakes.scripted_llm import ScriptedLLM
from tests.unit.agents.test_graph import (
    CUSTOMER,
    OTHER_CUSTOMER,
    Harness,
    _final,
    _inside_untrusted,
    _tool,
)

pytestmark = pytest.mark.unit


def _spy_issues(harness: Harness) -> list[tuple[object, ...]]:
    """Conta emissões de token no store do grafo sem trocar a implementação."""
    issued: list[tuple[object, ...]] = []
    original = harness.tokens.issue

    async def spy(*args: object, **kwargs: object) -> str:
        issued.append(args)
        return await original(*args, **kwargs)

    harness.tokens.issue = spy  # type: ignore[method-assign]
    return issued


def _eligibility(eligible: bool, reason: str) -> object:
    def _respond(_: dict[str, object]) -> object:
        return CheckReturnEligibilityOutput(
            eligible=eligible,
            reason=reason,
            deadline=BASE_TIME if eligible else None,
        )

    return _respond


# ------------------------------------------------------------------ cancel_order


@pytest.mark.parametrize(
    "status", ["shipped", "delivered", "cancelled", "in_transit", "return_requested"]
)
async def test_cancel_de_pedido_nao_cancelavel_nao_emite_token(status: str):
    store = StoreStub({"O000017": CUSTOMER})
    store.status["O000017"] = status
    llm = ScriptedLLM(
        [
            _tool("cancel_order", {"order_id": "O000017"}),
            _final("Seu pedido não pode mais ser cancelado."),
        ]
    )
    harness = Harness(llm, FakeRouter("cancel_order"), store)
    issued = _spy_issues(harness)

    state = await harness.turn("quero cancelar o pedido O000017")

    assert issued == []
    assert state["pending_action"] is None
    assert store.real_calls("cancel_order") == []
    assert len(llm.calls) == 2
    second_prompt = " ".join(m.content for m in llm.calls[1])
    assert _inside_untrusted(second_prompt, "not_cancelable")
    assert state["reply"] == "Seu pedido não pode mais ser cancelado."


async def test_cancel_de_pedido_de_outro_cliente_vira_not_found_sem_token_e_sem_vazar():
    store = StoreStub({"O000002": OTHER_CUSTOMER})
    llm = ScriptedLLM(
        [_tool("cancel_order", {"order_id": "O000002"}), _final("Não encontrei esse pedido.")]
    )
    harness = Harness(llm, FakeRouter("cancel_order"), store)
    issued = _spy_issues(harness)

    await harness.turn("cancela o O000002")

    assert issued == []
    assert store.real_calls("cancel_order") == []
    second_prompt = " ".join(m.content for m in llm.calls[1])
    assert _inside_untrusted(second_prompt, "not_found")
    assert OTHER_CUSTOMER not in second_prompt
    assert "pertence" not in second_prompt.lower()


@pytest.mark.parametrize("status", ["pending_payment", "paid", "processing"])
async def test_cancel_de_pedido_proprio_cancelavel_propoe_depois_da_leitura(status: str):
    store = StoreStub({"O000014": CUSTOMER})
    store.status["O000014"] = status
    llm = ScriptedLLM([_tool("cancel_order", {"order_id": "O000014"})])
    harness = Harness(llm, FakeRouter("cancel_order"), store)
    issued = _spy_issues(harness)

    state = await harness.turn("quero cancelar o pedido O000014")

    assert len(issued) == 1
    assert state["pending_action"] is not None
    assert state["pending_action"]["tool_name"] == "cancel_order"
    # a leitura de pré-checagem aconteceu antes de qualquer proposta
    assert store.calls[0][1] == "get_order_status"
    assert store.real_calls("cancel_order") == []


async def test_falha_transitoria_na_pre_checagem_devolve_erro_sem_token():
    store = StoreStub(
        {"O000014": CUSTOMER},
        tool_results={
            "get_order_status": lambda _: ToolError(
                code=ToolErrorCode.UPSTREAM_UNAVAILABLE, message="loja indisponível", retryable=True
            )
        },
    )
    llm = ScriptedLLM(
        [_tool("cancel_order", {"order_id": "O000014"}), _final("Tente novamente em instantes.")]
    )
    harness = Harness(llm, FakeRouter("cancel_order"), store)
    issued = _spy_issues(harness)

    state = await harness.turn("cancela o O000014")

    assert issued == []
    assert state["pending_action"] is None
    second_prompt = " ".join(m.content for m in llm.calls[1])
    assert ("upstream_unavailable" in second_prompt) or ("not_found" in second_prompt)


# ------------------------------------------------------------------ open_return


@pytest.mark.parametrize("reason", ["deadline_exceeded", "not_delivered"])
async def test_open_return_nao_elegivel_nao_emite_token(reason: str):
    store = StoreStub(
        {"O000004": CUSTOMER},
        tool_results={"check_return_eligibility": _eligibility(False, reason)},
    )
    llm = ScriptedLLM(
        [
            _tool(
                "open_return",
                {"order_id": "O000004", "sku": "P0056-45-MARROM", "reason": "tamanho"},
            ),
            _final("Infelizmente o prazo de devolução expirou."),
        ]
    )
    harness = Harness(llm, FakeRouter("return_request"), store)
    issued = _spy_issues(harness)

    state = await harness.turn("quero devolver o item do O000004")

    assert issued == []
    assert state["pending_action"] is None
    assert store.real_calls("open_return") == []
    second_prompt = " ".join(m.content for m in llm.calls[1])
    assert _inside_untrusted(second_prompt, "not_eligible")
    assert _inside_untrusted(second_prompt, reason)


async def test_open_return_elegivel_propoe():
    store = StoreStub(
        {"O000001": CUSTOMER},
        tool_results={"check_return_eligibility": _eligibility(True, "ok")},
    )
    llm = ScriptedLLM(
        [_tool("open_return", {"order_id": "O000001", "sku": "P0168-GG-AZUL", "reason": "tamanho"})]
    )
    harness = Harness(llm, FakeRouter("return_request"), store)
    issued = _spy_issues(harness)

    state = await harness.turn("quero devolver o item do O000001")

    assert len(issued) == 1
    assert state["pending_action"] is not None
    assert state["pending_action"]["tool_name"] == "open_return"
    assert store.real_calls("open_return") == []


async def test_open_return_de_pedido_de_outro_cliente_nao_propoe():
    store = StoreStub({"O000002": OTHER_CUSTOMER})
    llm = ScriptedLLM(
        [
            _tool("open_return", {"order_id": "O000002", "sku": "P0168-GG-AZUL", "reason": "x"}),
            _final("Não encontrei esse pedido."),
        ]
    )
    harness = Harness(llm, FakeRouter("return_request"), store)
    issued = _spy_issues(harness)

    state = await harness.turn("devolver o O000002")

    assert issued == []
    assert state["pending_action"] is None
    second_prompt = " ".join(m.content for m in llm.calls[1])
    assert _inside_untrusted(second_prompt, "not_found")
    assert OTHER_CUSTOMER not in second_prompt


async def test_pre_checagem_conta_um_passo_por_tool_call_do_llm():
    store = StoreStub({"O000017": CUSTOMER})
    store.status["O000017"] = "shipped"
    llm = ScriptedLLM(
        [_tool("cancel_order", {"order_id": "O000017"}), _final("Não posso cancelar.")]
    )
    harness = Harness(llm, FakeRouter("cancel_order"), store)

    state = await harness.turn("cancela o O000017")

    # 1 tool_call do LLM = 1 passo: o LLM recebe o erro e responde no passo seguinte
    assert len(llm.calls) == 2
    assert state["reply"] == "Não posso cancelar."
