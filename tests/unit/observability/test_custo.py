"""Custo do LLM em spans e métricas (Fase 09, meta "custo por conversa medido e publicado").

Nomes fixados:
- span `llm.complete`: `gen_ai.usage.cost_usd` só quando `LLMResult.cost_usd` é conhecido;
- contador `llm.cost.usd` com `provider` e `model`;
- span `conversation.turn`: `conversation.turn.cost_usd` = soma das chamadas do turno, ausente
  se alguma chamada tiver custo `None`;
- histograma `conversation.turn.cost`, um ponto por turno de custo conhecido;
- nenhuma métrica de custo leva `conversation_id` (cardinalidade e privacidade).
"""

from typing import Any

import pytest

from tests.fakes.agents import FakeRouter, StoreStub
from tests.fakes.graph import CUSTOMER, CostedLLM, GraphHarness, final, tool_call
from tests.fakes.telemetry import collected

pytestmark = pytest.mark.unit

CONV = "conv-custo-1"
MODEL = "modelo-custo"


async def _turn(costs: list[float | None], spans: Any) -> list[Any]:
    llm = CostedLLM(
        "primario",
        [tool_call("get_order_status", {"order_id": "O000001"}), final("Está a caminho.")],
        costs,
        model=MODEL,
    )
    harness = GraphHarness(llm, StoreStub({"O000001": CUSTOMER}), FakeRouter("order_status"))

    await harness.turn(CONV, "onde está meu pedido O000001?", message_id="msg-custo-1")

    return list(spans.get_finished_spans())


def _named(finished: list[Any], name: str) -> list[Any]:
    return [s for s in finished if s.name == name]


def _llm_ok(finished: list[Any]) -> list[Any]:
    """Os dois `llm.complete` do turno, ambos respondidos (sem isso o teste seria vazio)."""
    llm_spans = _named(finished, "llm.complete")
    assert len(llm_spans) == 2
    assert all("gen_ai.response.model" in s.attributes for s in llm_spans)
    return llm_spans


async def test_span_llm_complete_leva_o_custo_conhecido(spans: Any):
    finished = await _turn([0.001, 0.002], spans)

    llm_spans = _named(finished, "llm.complete")
    assert len(llm_spans) == 2
    assert sorted(s.attributes["gen_ai.usage.cost_usd"] for s in llm_spans) == pytest.approx(
        [0.001, 0.002]
    )


async def test_custo_desconhecido_nao_vira_atributo(spans: Any):
    finished = await _turn([None, 0.002], spans)

    llm_spans = _llm_ok(finished)
    sem_custo = [s for s in llm_spans if "gen_ai.usage.cost_usd" not in s.attributes]
    assert len(sem_custo) == 1


async def test_turno_soma_o_custo_das_chamadas(spans: Any):
    finished = await _turn([0.001, 0.002], spans)

    (root,) = _named(finished, "conversation.turn")
    assert root.attributes["conversation.turn.cost_usd"] == pytest.approx(0.003)


async def test_turno_com_alguma_chamada_sem_custo_nao_tem_custo(spans: Any):
    finished = await _turn([0.001, None], spans)

    _llm_ok(finished)
    (root,) = _named(finished, "conversation.turn")
    assert "conversation.turn.cost_usd" not in root.attributes


async def test_contador_de_custo_por_provider_e_modelo(spans: Any, metric_reader: Any):
    await _turn([0.001, 0.002], spans)

    pontos = collected(metric_reader)["llm.cost.usd"]
    assert sum(p.value for p in pontos) == pytest.approx(0.003)
    assert {(p.attributes.get("provider"), p.attributes.get("model")) for p in pontos} == {
        ("primario", MODEL)
    }


async def test_histograma_de_custo_do_turno(spans: Any, metric_reader: Any):
    await _turn([0.001, 0.002], spans)

    pontos = collected(metric_reader)["conversation.turn.cost"]
    assert sum(p.count for p in pontos) == 1
    assert sum(p.sum for p in pontos) == pytest.approx(0.003)


async def test_turno_de_custo_desconhecido_nao_registra_histograma(spans: Any, metric_reader: Any):
    _llm_ok(await _turn([None, 0.002], spans))

    metricas = collected(metric_reader)
    assert sum(p.count for p in metricas.get("conversation.turn.cost", [])) == 0
    # A chamada de custo conhecido ainda entra no contador.
    assert sum(p.value for p in metricas["llm.cost.usd"]) == pytest.approx(0.002)


async def test_metricas_de_custo_nao_levam_conversation_id(spans: Any, metric_reader: Any):
    await _turn([0.001, 0.002], spans)

    metricas = collected(metric_reader)
    pontos = metricas["llm.cost.usd"] + metricas["conversation.turn.cost"]
    assert pontos
    for ponto in pontos:
        assert "conversation_id" not in ponto.attributes
        assert CONV not in {str(v) for v in ponto.attributes.values()}
