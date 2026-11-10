"""Privacidade dos traces (ADR 0018 e 0013): por padrão só identificadores e números.

Cada texto sentinela é único; procura-se em nomes, atributos, eventos e status de todos os spans.
- Sem `OTEL_CAPTURE_CONTENT`: nada do texto do cliente, da resposta, do prompt, dos argumentos
  de ferramenta nem do token de confirmação.
- Com `OTEL_CAPTURE_CONTENT=true`: prompt e resposta aparecem nos spans `llm.complete`; o token
  de confirmação continua ausente.
"""

from typing import Any

import pytest

from tests.fakes.agents import FakeRouter, StoreStub, policy_chunk
from tests.fakes.graph import CUSTOMER, GraphHarness, ProviderLLM, final, tool_call
from tests.fakes.telemetry import all_span_text

pytestmark = pytest.mark.unit

TEXTO_CLIENTE = "sentinela-cliente-7f3a91"
TEXTO_RESPOSTA = "sentinela-resposta-c0d4e2"
TEXTO_ARGUMENTO = "sentinela-argumento-5b8e17"
TRECHO_DO_PROMPT = "Fale em português do Brasil"


async def _politica(spans: Any) -> list[Any]:
    store = StoreStub({}, search_chunks=(policy_chunk("troca#0"),))
    llm = ProviderLLM(
        "primario",
        [
            tool_call("search_policies", {"query": TEXTO_ARGUMENTO}),
            final(f"Você tem 7 dias. {TEXTO_RESPOSTA}", ["troca#0"]),
        ],
    )
    harness = GraphHarness(llm, store, FakeRouter("policy_question"))

    state = await harness.turn(
        "conv-priv-1", f"qual o prazo de troca? {TEXTO_CLIENTE}", message_id="msg-priv-1"
    )

    assert TEXTO_RESPOSTA in state["reply"]
    assert store.real_calls("search_policies") == [{"query": TEXTO_ARGUMENTO}]
    return list(spans.get_finished_spans())


async def _token_de_confirmacao(spans: Any) -> tuple[str, list[Any]]:
    store = StoreStub({"O000014": CUSTOMER})
    llm = ProviderLLM("primario", [tool_call("cancel_order", {"order_id": "O000014"})])
    harness = GraphHarness(llm, store, FakeRouter("cancel_order"))

    await harness.turn("conv-priv-2", "quero cancelar o pedido O000014", message_id="msg-priv-2")
    await harness.turn("conv-priv-2", "sim", message_id="msg-priv-3")

    (cancel,) = store.real_calls("cancel_order")
    return cancel["confirmation_token"], list(spans.get_finished_spans())


async def test_sem_captura_nenhum_span_tem_texto_do_cliente_resposta_prompt_ou_argumento(
    spans: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OTEL_CAPTURE_CONTENT", raising=False)

    finished = await _politica(spans)

    assert finished, "o turno deveria ter gerado spans"
    texto = all_span_text(finished)
    for sentinela in (TEXTO_CLIENTE, TEXTO_RESPOSTA, TEXTO_ARGUMENTO, TRECHO_DO_PROMPT):
        assert sentinela not in texto


async def test_sem_captura_token_de_confirmacao_nao_aparece(
    spans: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OTEL_CAPTURE_CONTENT", raising=False)

    token, finished = await _token_de_confirmacao(spans)

    assert finished
    assert token not in all_span_text(finished)


async def test_com_captura_prompt_e_resposta_aparecem_no_span_de_llm(
    spans: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("OTEL_CAPTURE_CONTENT", "true")

    finished = await _politica(spans)

    texto_llm = all_span_text(s for s in finished if s.name == "llm.complete")
    assert TEXTO_CLIENTE in texto_llm
    assert TRECHO_DO_PROMPT in texto_llm
    assert TEXTO_RESPOSTA in texto_llm


async def test_com_captura_token_de_confirmacao_continua_ausente(
    spans: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("OTEL_CAPTURE_CONTENT", "true")

    token, finished = await _token_de_confirmacao(spans)

    assert any(s.name == "llm.complete" for s in finished)
    assert token not in all_span_text(finished)
