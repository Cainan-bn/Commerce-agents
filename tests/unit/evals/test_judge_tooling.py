"""Ferramental do juiz: --judge no relatório, traces.jsonl, calibrate-export e calibrate."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.traces import call, scenario, trace, turn

pytestmark = pytest.mark.unit

SCORE = json.dumps(
    {
        "criteria": {"utilidade": 4, "fidelidade": 4, "tom": 4, "concisao": 4},
        "rationale": "ok",
    }
)


def _scenarios_and_traces() -> tuple[dict[str, Any], dict[str, Any]]:
    scenarios = {
        "PED-001": scenario(scenario_id="PED-001", category="pedidos"),
        "POL-001": scenario(scenario_id="POL-001", category="politicas"),
        "PED-002": scenario(scenario_id="PED-002", category="pedidos"),
    }
    traces = {
        "PED-001": trace(
            "PED-001",
            turns=[turn(text="onde está?", reply="a caminho")],
            tool_calls=[
                call("get_order_status", {"order_id": "O1", "confirmation_token": "SEGREDO"})
            ],
            policy_citations=["troca#0"],
        ),
        "POL-001": trace("POL-001", turns=[turn(text="troca?", reply="7 dias")]),
        "PED-002": trace("PED-002", handoff_events=["urgente"]),
    }
    return scenarios, traces


def _report(judge: Any = None) -> dict[str, Any]:
    from evals.metrics import aggregate, evaluate
    from evals.report import build_report

    scenarios, traces = _scenarios_and_traces()
    results = [evaluate(traces[i], scenarios[i]) for i in scenarios]
    return build_report(
        label="t",
        commit="abc",
        corpus_version="v",
        models={"agent": "a", "judge": "j"},
        temperature=0.0,
        aggregate=aggregate(results),
        results=results,
        scenarios=scenarios,
        traces=traces,
        judge=judge,
    )


async def _judged() -> dict[str, Any]:
    from evals.judge import judge_scenario

    scenarios, traces = _scenarios_and_traces()
    provider = ScriptedLLM([SCORE, SCORE])
    return {i: await judge_scenario(provider, scenarios[i], traces[i]) for i in scenarios}


# ----------------------------------------------------------------- relatório


def test_sem_judge_o_relatorio_nao_tem_secao_do_juiz():
    from evals.report import render_markdown

    report = _report()

    assert "judge" not in report
    assert "Juiz" not in render_markdown(report)


async def test_com_judge_o_relatorio_traz_media_julgados_pulados_e_categorias():
    from evals.report import render_markdown

    report = _report(await _judged())

    assert report["judge"]["mean_overall"] == 4.0
    assert report["judge"]["judged"] == 2
    assert report["judge"]["skipped"] == 1
    assert report["judge"]["by_category"]["politicas"]["judged"] == 1
    markdown = render_markdown(report)
    assert "## Juiz (sinal secundário)" in markdown
    assert "politicas" in markdown


def test_secao_do_juiz_sem_nenhum_julgado_mostra_traco():
    from evals.judge import JudgeResult
    from evals.report import render_markdown

    report = _report({"PED-001": JudgeResult(None, "judge_unavailable")})

    assert "nota geral média: -" in render_markdown(report)


# ----------------------------------------------------------------- traces.jsonl


async def test_traces_jsonl_nao_tem_token_argumentos_nem_expected(tmp_path: Path):
    from evals.report import build_trace_rows, write_traces

    scenarios, traces = _scenarios_and_traces()
    rows = build_trace_rows(scenarios, traces, await _judged())

    path = write_traces(rows, tmp_path, stem="20260607-t")
    lines = path.read_text(encoding="utf-8").splitlines()

    assert path.name == "20260607-t.traces.jsonl"
    assert len(lines) == 3
    texto = "\n".join(lines)
    assert "SEGREDO" not in texto
    assert "confirmation_token" not in texto
    assert "order_id" not in texto
    first = json.loads(lines[0])
    assert first["tool_calls"] == [{"name": "get_order_status", "ok": True, "error_code": None}]
    assert first["judge"]["overall"] == 4
    assert json.loads(lines[2])["judge"] == {"skipped_reason": "not_resolved"}
    assert json.loads(lines[2])["outcome"] == "handoff"


def test_traces_sem_juiz_nao_tem_campo_judge():
    from evals.report import build_trace_rows

    scenarios, traces = _scenarios_and_traces()

    assert all("judge" not in row for row in build_trace_rows(scenarios, traces))


# ----------------------------------------------------------------- calibrate-export


def _rows() -> list[dict[str, Any]]:
    from evals.report import build_trace_rows

    scenarios = {}
    traces = {}
    for i in range(6):
        sid, cat = f"PED-{i}", "pedidos"
        scenarios[sid] = scenario(scenario_id=sid, category=cat)
        traces[sid] = trace(sid, turns=[turn(text=f"p{i}", reply=f"r{i}")])
    for i in range(3):
        sid = f"POL-{i}"
        scenarios[sid] = scenario(scenario_id=sid, category="politicas")
        traces[sid] = trace(sid, turns=[turn(text=f"q{i}", reply=f"s{i}")])
    scenarios["HAN-1"] = scenario(scenario_id="HAN-1", category="handoff")
    traces["HAN-1"] = trace("HAN-1", handoff_events=["x"])
    return build_trace_rows(scenarios, traces)


def test_amostra_e_deterministica_estratificada_e_so_de_resolvidas():
    from evals.calibration import sample_for_labeling

    first = sample_for_labeling(_rows(), 4)
    second = sample_for_labeling(list(reversed(_rows())), 4)

    assert first == second
    assert len(first) == 4
    assert {r["category"] for r in first} == {"pedidos", "politicas"}
    assert all(r["id"] != "HAN-1" for r in first)


def test_amostra_nao_tem_juiz_nem_expected_e_tem_o_formato_contratado():
    from evals.calibration import sample_for_labeling

    row = sample_for_labeling(_rows(), 1)[0]

    assert set(row) == {"id", "category", "conversation", "tools"}
    assert set(row["conversation"][0]) == {"user", "agent"}


def test_amostra_maior_que_o_disponivel_devolve_tudo():
    from evals.calibration import sample_for_labeling

    assert len(sample_for_labeling(_rows(), 100)) == 9


# ----------------------------------------------------------------- calibrate


async def test_calibrate_conta_pares_concordancia_e_discordancias():
    from evals.calibration import calibrate, format_calibration

    rows = _rows()
    labels = [
        {"id": "PED-0", "overall": 4},
        {"id": "PED-1", "overall": 1},
        {"id": "HAN-1", "overall": 3},
        {"id": "INEXISTENTE", "overall": 3},
    ]

    result = await calibrate(ScriptedLLM([SCORE, SCORE]), rows, labels)

    assert result.pairs == [("PED-0", 4, 4), ("PED-1", 1, 4)]
    assert result.unjudged == ["HAN-1", "INEXISTENTE"]
    assert result.agreement == pytest.approx(0.5)
    texto = format_calibration("v1", result)
    assert "pares: 2" in texto
    assert "50.0%" in texto
    assert "PED-1 rótulo=1 juiz=4" in texto


async def test_calibrate_sem_pares_nao_levanta():
    from evals.calibration import calibrate, format_calibration

    result = await calibrate(
        ScriptedLLM([LLMUnavailableError("fora")]), _rows(), [{"id": "PED-0", "overall": 3}]
    )

    assert result.agreement is None
    assert "n/d" in format_calibration("v1", result)


# ----------------------------------------------------------------- CLI


def test_cli_run_com_judge_grava_secao_e_traces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from evals import __main__ as cli
    from evals.judge import JudgeResult, JudgeScore

    async def fake_run_all(scenarios: Any, environ: Any) -> dict[str, Any]:
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    async def fake_judge_all(scenarios: Any, traces: Any, environ: Any) -> dict[str, Any]:
        score = JudgeScore({"utilidade": 4, "fidelidade": 4, "tom": 4, "concisao": 4}, "ok")
        return {s.id: JudgeResult(score, None) for s in scenarios}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "_judge_all", fake_judge_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    code = cli.main(["run", "--label", "j", "--subset", "quick", "--judge"], environ={})

    assert code == 0
    assert "Juiz (sinal secundário)" in next(tmp_path.glob("*-j.md")).read_text(encoding="utf-8")
    assert len(list(tmp_path.glob("*-j.traces.jsonl"))) == 1


def test_cli_run_sem_judge_nao_chama_o_juiz_e_grava_traces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from evals import __main__ as cli

    async def fake_run_all(scenarios: Any, environ: Any) -> dict[str, Any]:
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    def boom(*args: Any) -> Any:
        raise AssertionError("juiz não deveria rodar")

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "_judge_all", boom)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(["run", "--label", "s", "--subset", "quick"], environ={})

    assert "Juiz" not in next(tmp_path.glob("*-s.md")).read_text(encoding="utf-8")
    assert len(list(tmp_path.glob("*-s.traces.jsonl"))) == 1


def test_cli_calibrate_export_e_calibrate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    from evals import __main__ as cli
    from evals.calibration import write_jsonl

    from commerce_agents.infrastructure.llm import openai_compatible

    traces_path = tmp_path / "t.traces.jsonl"
    write_jsonl(_rows(), traces_path)
    out = tmp_path / "sub" / "to_label.jsonl"

    assert (
        cli.main(["calibrate-export", "--traces", str(traces_path), "--n", "3", "--out", str(out)])
        == 0
    )
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3

    labels = tmp_path / "labels.jsonl"
    write_jsonl([{"id": "PED-0", "overall": 4}], labels)
    monkeypatch.setattr(
        openai_compatible, "build_judge_provider_from_env", lambda env: ScriptedLLM([SCORE])
    )
    code = cli.main(
        ["calibrate", "--traces", str(traces_path), "--labels", str(labels), "--label", "v1"],
        environ={},
    )

    assert code == 0
    assert "pares: 1" in capsys.readouterr().out


async def test_judge_all_usa_o_provider_do_juiz(monkeypatch: pytest.MonkeyPatch):
    from evals import __main__ as cli

    from commerce_agents.infrastructure.llm import openai_compatible

    scenarios, traces = _scenarios_and_traces()
    monkeypatch.setattr(
        openai_compatible, "build_judge_provider_from_env", lambda env: ScriptedLLM([SCORE, SCORE])
    )

    results = await cli._judge_all(list(scenarios.values()), traces, {})

    assert sum(1 for r in results.values() if r.score is not None) == 2


# ----------------------------------------------------------------- calibrate: concorrência


class _SlowJudge:
    """Provider lento; devolve nota fixa e registra o pico de chamadas simultâneas."""

    def __init__(self, delay: float, fail_on: int | None = None) -> None:
        self._delay = delay
        self._fail_on = fail_on
        self._calls = 0
        self.running = 0
        self.peak = 0

    async def complete(self, messages: Any, *, max_tokens: int) -> Any:
        from commerce_agents.application.dto.views import LLMResult

        self._calls += 1
        number = self._calls
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(self._delay)
        finally:
            self.running -= 1
        if number == self._fail_on:
            raise LLMUnavailableError("fora")
        return LLMResult(content=SCORE, model="slow", input_tokens=1, output_tokens=1)


def _labels(n: int) -> list[dict[str, Any]]:
    return [{"id": f"PED-{i}", "overall": 4} for i in range(n)]


async def test_calibrate_julga_em_rodadas_de_concurrency_e_mantem_a_ordem():
    from evals.calibration import calibrate

    rows = [r for r in _rows() if r["id"].startswith("PED-")] + [
        {**_rows()[0], "id": f"PED-{i}"} for i in (6, 7)
    ]
    provider = _SlowJudge(delay=0.2)

    started = time.monotonic()
    result = await calibrate(provider, rows, _labels(8), concurrency=4)
    elapsed = time.monotonic() - started

    assert elapsed < 0.2 * 3  # 2 rodadas, não 8 em série
    assert provider.peak == 4
    assert [p[0] for p in result.pairs] == [f"PED-{i}" for i in range(8)]


async def test_calibrate_falha_de_um_julgamento_nao_interrompe_os_demais():
    from evals.calibration import calibrate

    rows = [r for r in _rows() if r["id"].startswith("PED-")]

    result = await calibrate(_SlowJudge(delay=0, fail_on=2), rows, _labels(4), concurrency=1)

    assert len(result.pairs) == 3
    assert len(result.unjudged) == 1


async def test_calibrate_chama_on_progress_por_conversa_concluida():
    from evals.calibration import calibrate

    rows = [r for r in _rows() if r["id"].startswith("PED-")]
    eventos: list[tuple[int, int, str, bool]] = []

    await calibrate(
        _SlowJudge(delay=0),
        rows,
        [*_labels(2), {"id": "INEXISTENTE", "overall": 3}],
        on_progress=lambda done, total, sid, ok: eventos.append((done, total, sid, ok)),
    )

    assert [e[0] for e in eventos] == [1, 2, 3]
    assert {e[1] for e in eventos} == {3}
    assert ("INEXISTENTE", False) in [(e[2], e[3]) for e in eventos]
