"""Cobertura extra das métricas: percentis e tokens por cenário."""

import pytest
from evals.trace import LLMCallRecord

from tests.fakes.traces import scenario, trace, turn

pytestmark = pytest.mark.unit


def test_evaluate_soma_tokens_e_calcula_percentis():
    from evals.metrics import evaluate

    tr = trace(turns=[turn()])
    tr.llm_calls = [
        LLMCallRecord(model="m", input_tokens=10, output_tokens=5, latency_ms=ms)
        for ms in (100, 200, 300, 400)
    ]

    result = evaluate(tr, scenario())

    assert result.tokens == 60
    assert result.latency_p50_ms == 200.0
    assert result.latency_p95_ms == 400.0


def test_evaluate_sem_chamadas_tem_latencia_zero():
    from evals.metrics import evaluate

    assert evaluate(trace(turns=[turn()]), scenario()).latency_p50_ms == 0.0


def test_aggregate_vazio():
    from evals.metrics import aggregate

    result = aggregate([])

    assert (result.total, result.rates) == (0, {})
