"""Buckets dos histogramas na escala das metas (TASK-09-03e).

Os limites padrão do SDK (0, 5, 10, 25, ..., 10000) tornam o p95 inútil: todo turno abaixo de 5 s
cai em (0, 5] e `histogram_quantile(0.95)` devolve 4,75 s. Contrato fixado: cada histograma
declara `explicit_bucket_boundaries_advisory` no `create_histogram` (sem View):
- `conversation.turn.duration` e `llm.duration` (s): 0.05 ... 30, com 4 exato (meta do turno);
- `tool.duration` (s): 0.005 ... 2.5;
- `conversation.turn.cost` (USD): 0.0001 ... 1.
"""

from typing import Any

import pytest

from tests.fakes.telemetry import collected

pytestmark = pytest.mark.unit

SECONDS = (0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 30)
TOOL_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1, 2.5)
TURN_COST_USD = (0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1)


def _telemetry() -> Any:
    from commerce_agents.infrastructure import telemetry

    return telemetry


def _record(instrument: str, value: float, metric_reader: Any) -> Any:
    getattr(_telemetry(), instrument).record(value, {"channel": "web"})
    return collected(metric_reader)


def _point(metrics: dict[str, list[Any]], name: str) -> Any:
    (point,) = metrics[name]
    return point


@pytest.mark.parametrize(
    ("instrument", "name", "bounds"),
    [
        ("TURN_DURATION", "conversation.turn.duration", SECONDS),
        ("LLM_DURATION", "llm.duration", SECONDS),
        ("TOOL_DURATION", "tool.duration", TOOL_SECONDS),
        ("TURN_COST", "conversation.turn.cost", TURN_COST_USD),
    ],
)
def test_histograma_declara_os_limites_da_escala_da_meta(
    instrument: str, name: str, bounds: tuple[float, ...], metric_reader: Any
):
    point = _point(_record(instrument, bounds[0] / 2, metric_reader), name)

    assert tuple(point.explicit_bounds) == pytest.approx(bounds)


def test_meta_de_4_s_e_limite_exato_do_turno():
    assert 4 in SECONDS


def test_turno_de_800_ms_cai_no_bucket_de_075_a_1_s(metric_reader: Any):
    point = _point(_record("TURN_DURATION", 0.8, metric_reader), "conversation.turn.duration")

    bounds = list(point.explicit_bounds)
    assert bounds == pytest.approx(list(SECONDS))
    # bucket_counts[i] conta (bounds[i-1], bounds[i]]: (0.75, 1] é o índice de 1.
    index = bounds.index(1)
    assert bounds[index - 1] == pytest.approx(0.75)
    assert list(point.bucket_counts) == [1 if i == index else 0 for i in range(len(bounds) + 1)]


def test_turno_acima_da_meta_cai_acima_de_4_s(metric_reader: Any):
    point = _point(_record("TURN_DURATION", 4.2, metric_reader), "conversation.turn.duration")

    bounds = list(point.explicit_bounds)
    assert bounds == pytest.approx(list(SECONDS))
    index = bounds.index(5)
    assert bounds[index - 1] == pytest.approx(4)
    assert point.bucket_counts[index] == 1
