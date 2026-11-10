"""Relatório e CLI: montagem do relatório, carga de cenários e execução com runner falso."""

from pathlib import Path
from typing import Any

import pytest

from tests.fakes.traces import scenario, trace, turn

pytestmark = pytest.mark.unit


def _built() -> dict[str, Any]:
    from evals.metrics import aggregate, evaluate
    from evals.report import build_report

    ok_scn = scenario(scenario_id="PED-001")
    bad_scn = scenario(scenario_id="PED-002", must_mention=["zzz"])
    broken_scn = scenario(scenario_id="PED-003")
    traces = {
        "PED-001": trace("PED-001", turns=[turn()]),
        "PED-002": trace("PED-002", turns=[turn(reply="resposta " * 50)]),
        "PED-003": trace("PED-003", infra_error="llm indisponível"),
    }
    scenarios = {s.id: s for s in (ok_scn, bad_scn, broken_scn)}
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
    )


def test_build_report_marca_falha_com_trecho_e_infra_error_a_parte():
    report = _built()
    by_id = {s["id"]: s for s in report["scenarios"]}

    assert "must_mention" in by_id["PED-002"]["failure_excerpt"]
    assert len(by_id["PED-002"]["failure_excerpt"]) < 300
    assert by_id["PED-003"]["infra_error"] == "llm indisponível"
    assert report["infra_errors"] == 1
    assert report["cost_usd"] is None


def test_markdown_lista_falhas_e_infra(tmp_path: Path):
    from evals.report import render_markdown

    md = render_markdown(_built())

    assert "PED-002" in md and "infra: llm indisponível" in md


def test_markdown_sem_falhas_diz_nenhuma():
    from evals.report import render_markdown

    report = _built()
    report["scenarios"] = [s for s in report["scenarios"] if s["scenario_pass"]]

    assert "Nenhuma." in render_markdown(report)


def test_compare_ignora_cenarios_novos_e_iguais():
    from evals.report import compare

    before = {"scenarios": [{"id": "A", "scenario_pass": True}]}
    after = {
        "scenarios": [
            {"id": "A", "scenario_pass": True},
            {"id": "B", "scenario_pass": False},
        ]
    }

    assert compare(before, after) == {"improved": [], "worsened": []}


def test_load_scenarios_dev_completo_e_quick():
    from evals import __main__ as cli

    dev = cli.load_scenarios("dev", "all", environ={})
    quick = cli.load_scenarios("dev", "quick", environ={})

    assert len(dev) == 54
    assert sorted(s.id for s in quick) == sorted(cli.QUICK_SUBSET)


def test_load_scenarios_holdout_le_a_pasta_do_ambiente(tmp_path: Path):
    from evals import __main__ as cli

    assert cli.load_scenarios("holdout", "all", environ={"EVAL_HOLDOUT_DIR": str(tmp_path)}) == []


def test_corpus_version_muda_com_o_conteudo(tmp_path: Path):
    from evals import __main__ as cli

    (tmp_path / "a.md").write_text("um", encoding="utf-8")
    first = cli._corpus_version(tmp_path)
    (tmp_path / "a.md").write_text("dois", encoding="utf-8")

    assert first != cli._corpus_version(tmp_path)
    assert cli._commit()


def test_main_executa_e_grava_relatorio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from evals import __main__ as cli

    async def fake_run_all(scenarios: Any, environ: Any, concurrency: int = 4) -> dict[str, Any]:
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    code = cli.main(["run", "--label", "fake", "--subset", "quick"], environ={"LLM_MODEL": "m"})

    assert code == 0
    assert len(list(tmp_path.glob("*-fake.json"))) == 1
    assert len(list(tmp_path.glob("*-fake.md"))) == 1


async def test_run_all_isola_o_ambiente_por_cenario(monkeypatch: pytest.MonkeyPatch):
    import json

    from evals import __main__ as cli

    from commerce_agents.infrastructure.llm import openai_compatible
    from tests.fakes.evals import make_eval_deps
    from tests.fakes.scripted_llm import ScriptedLLM

    built: list[dict[str, Any]] = []

    def fake_real_deps(**kwargs: Any) -> Any:
        built.append(kwargs)
        final = json.dumps({"type": "final", "text": "ok", "citations": []})
        return make_eval_deps([final])

    monkeypatch.setattr(cli, "build_real_deps", fake_real_deps)
    monkeypatch.setattr(openai_compatible, "build_provider_from_env", lambda env: ScriptedLLM([]))
    scenarios = [scenario(scenario_id="A-1"), scenario(scenario_id="A-2")]

    traces = await cli._run_all(scenarios, {"LLM_MODEL": "m", "LLM_PROVIDER": "p"})

    assert sorted(traces) == ["A-1", "A-2"]
    assert len(built) == 2
    assert built[0]["model"] == "m"


def test_commit_desconhecido_sem_git(monkeypatch: pytest.MonkeyPatch):
    import subprocess

    from evals import __main__ as cli

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("sem git")

    monkeypatch.setattr(subprocess, "run", boom)

    assert cli._commit() == "desconhecido"
