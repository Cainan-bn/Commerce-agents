"""Tempo por fase no relatório: `timing_s` no JSON e linha "tempo (s): ..." no Markdown.

O relógio é injetado (`main(..., clock=...)`), então as durações são exatas nos testes.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.traces import scenario, trace, turn

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def avanca(self, segundos: float) -> None:
        self.now += segundos


def _cli():  # type: ignore[no-untyped-def]
    from evals import __main__ as cli

    return cli


def _report(timing: dict[str, float] | None = None) -> dict[str, Any]:
    from evals.metrics import aggregate, evaluate
    from evals.report import build_report

    scn = scenario(scenario_id="PED-001")
    traces = {"PED-001": trace("PED-001", turns=[turn()])}
    results = [evaluate(traces["PED-001"], scn)]
    return build_report(
        label="t",
        commit="abc",
        corpus_version="v",
        models={"agent": "a", "judge": "j"},
        temperature=0.0,
        aggregate=aggregate(results),
        results=results,
        scenarios={"PED-001": scn},
        traces=traces,
        timing=timing,
    )


TEMPO = {"agent": 12.5, "retry": 3.0, "judge": 4.0, "total": 20.0}


def test_json_traz_tempo_por_fase():
    report = _report(timing=TEMPO)

    assert report["timing_s"] == TEMPO


def test_markdown_traz_linha_de_tempo_por_fase():
    from evals.report import render_markdown

    md = render_markdown(_report(timing=TEMPO))

    assert "- tempo (s): agente 12.5, reexecucao 3.0, juiz 4.0, total 20.0" in md


def test_write_report_grava_tempo_no_json_e_no_markdown(tmp_path: Path):
    from evals.report import write_report

    json_path, md_path = write_report(_report(timing=TEMPO), tmp_path, timestamp="20261109-100000")

    assert json.loads(json_path.read_text(encoding="utf-8"))["timing_s"] == TEMPO
    assert "tempo (s): agente 12.5" in md_path.read_text(encoding="utf-8")


def test_main_mede_agente_reexecucao_juiz_e_total_com_relogio_injetado(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from evals.retry import InfraRetry

    cli = _cli()
    relogio = FakeClock()

    async def fake_run_all(scenarios: Any, environ: Any, concurrency: int = 4) -> dict[str, Any]:
        relogio.avanca(10.0)
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    async def fake_retry(scenarios: Any, traces: Any, run: Any, **kwargs: Any) -> InfraRetry:
        relogio.avanca(3.0)
        return InfraRetry(traces=traces, rounds=0, recovered=0, extra_cost_usd=0.0)

    async def fake_judge_all(
        scenarios: Any, traces: Any, environ: Any, concurrency: int = 4
    ) -> dict[str, Any]:
        relogio.avanca(4.0)
        return {}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "retry_infra", fake_retry)
    monkeypatch.setattr(cli, "_judge_all", fake_judge_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(
        ["run", "--label", "fake", "--subset", "quick", "--judge"],
        environ={},
        clock=relogio,
    )

    timing = json.loads(next(tmp_path.glob("*-fake.json")).read_text(encoding="utf-8"))["timing_s"]
    assert timing == {"agent": 10.0, "retry": 3.0, "judge": 4.0, "total": 17.0}


def test_main_sem_judge_informa_juiz_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _cli()
    relogio = FakeClock()

    async def fake_run_all(scenarios: Any, environ: Any, concurrency: int = 4) -> dict[str, Any]:
        relogio.avanca(6.0)
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(
        ["run", "--label", "fake", "--subset", "quick", "--retry-infra", "0"],
        environ={},
        clock=relogio,
    )

    timing = json.loads(next(tmp_path.glob("*-fake.json")).read_text(encoding="utf-8"))["timing_s"]
    assert timing == {"agent": 6.0, "retry": 0.0, "judge": 0.0, "total": 6.0}
