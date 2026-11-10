"""Reexecução de cenários com erro de infraestrutura (`--retry-infra`)."""

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.traces import scenario, trace, turn

pytestmark = pytest.mark.unit


def _ok(sid: str, cost: float | None = None) -> Any:
    tr = trace(sid, turns=[turn()])
    tr.cost_usd = cost
    return tr


def _infra(sid: str, cost: float | None = None) -> Any:
    tr = trace(sid, infra_error="roteador indisponível")
    tr.cost_usd = cost
    return tr


class _Runner:
    """Executor falso: `script[sid]` é a lista de traces devolvidos a cada execução."""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: Counter[str] = Counter()
        self.concurrencies: list[int] = []

    async def __call__(self, scenarios: list[Any], concurrency: int) -> dict[str, Any]:
        self.concurrencies.append(concurrency)
        out = {}
        for s in scenarios:
            self.calls[s.id] += 1
            out[s.id] = self.script[s.id].pop(0)
        return out


async def _nao_dorme(seconds: float) -> None:
    return None


def _retry():  # type: ignore[no-untyped-def]
    from evals import retry

    return retry


async def test_cenario_que_falha_na_primeira_passada_e_passa_na_segunda_e_recuperado():
    scns = [scenario(scenario_id="A"), scenario(scenario_id="B")]
    first = {"A": _infra("A"), "B": _ok("B")}
    runner = _Runner({"A": [_ok("A")]})

    result = await _retry().retry_infra(scns, first, runner, rounds=2, pause_s=0, sleep=_nao_dorme)

    assert result.traces["A"].infra_error is None
    assert result.recovered == 1
    assert result.rounds == 1  # parou cedo: nada mais com erro de infraestrutura


async def test_cenario_que_falha_em_todas_as_rodadas_segue_infra_error():
    scns = [scenario(scenario_id="A")]
    runner = _Runner({"A": [_infra("A"), _infra("A")]})

    result = await _retry().retry_infra(
        scns, {"A": _infra("A")}, runner, rounds=2, pause_s=0, sleep=_nao_dorme
    )

    assert result.traces["A"].infra_error
    assert result.recovered == 0
    assert result.rounds == 2
    assert runner.calls["A"] == 2


async def test_cenario_sem_infra_error_nunca_e_reexecutado():
    scns = [scenario(scenario_id="A"), scenario(scenario_id="B", must_mention=["zzz"])]
    first = {"A": _infra("A"), "B": _ok("B")}  # B falha por regra do agente, não por infra
    runner = _Runner({"A": [_ok("A")]})

    await _retry().retry_infra(scns, first, runner, rounds=3, pause_s=0, sleep=_nao_dorme)

    assert runner.calls == Counter({"A": 1})


async def test_zero_rodadas_desliga_a_reexecucao():
    scns = [scenario(scenario_id="A")]
    runner = _Runner({})

    result = await _retry().retry_infra(
        scns, {"A": _infra("A")}, runner, rounds=0, pause_s=0, sleep=_nao_dorme
    )

    assert runner.calls == Counter()
    assert result.rounds == 0
    assert result.traces["A"].infra_error


async def test_reexecucao_usa_concorrencia_reduzida_e_pausa_entre_rodadas():
    pausas: list[float] = []

    async def sleep(seconds: float) -> None:
        pausas.append(seconds)

    scns = [scenario(scenario_id="A")]
    runner = _Runner({"A": [_infra("A"), _ok("A")]})

    await _retry().retry_infra(scns, {"A": _infra("A")}, runner, rounds=2, pause_s=7, sleep=sleep)

    assert runner.concurrencies == [2, 2]
    assert pausas == [7, 7]


async def test_custo_das_tentativas_descartadas_entra_no_extra():
    scns = [scenario(scenario_id="A"), scenario(scenario_id="B")]
    first = {"A": _infra("A", cost=0.5), "B": _infra("B", cost=0.25)}
    runner = _Runner({"A": [_ok("A", cost=1.0)], "B": [_infra("B", cost=0.125)]})

    result = await _retry().retry_infra(scns, first, runner, rounds=1, pause_s=0, sleep=_nao_dorme)

    # A: trace antigo (0.5) descartado; B: nova tentativa (0.125) descartada.
    assert result.extra_cost_usd == pytest.approx(0.625)
    assert result.traces["A"].cost_usd == 1.0
    assert result.traces["B"].cost_usd == 0.25


# ----------------------------------------------------------------- relatório


def _report(retry: Any) -> dict[str, Any]:
    from evals.metrics import aggregate, evaluate
    from evals.report import build_report

    scn = scenario(scenario_id="A")
    traces = {"A": _ok("A", cost=1.0)}
    results = [evaluate(traces["A"], scn)]
    return build_report(
        label="t",
        commit="c",
        corpus_version="v",
        models={"agent": "a", "judge": "j"},
        temperature=0.0,
        aggregate=aggregate(results),
        results=results,
        scenarios={"A": scn},
        traces=traces,
        infra_retry=retry,
    )


def test_relatorio_mostra_reexecucoes_e_soma_o_custo_extra():
    from evals.report import render_markdown
    from evals.retry import InfraRetry

    report = _report(InfraRetry(traces={}, rounds=2, recovered=3, extra_cost_usd=0.5))

    assert report["infra_retry"] == {"rounds": 2, "recovered": 3}
    assert report["cost_usd"] == pytest.approx(1.5)
    assert "reexecuções de infraestrutura: 2 rodadas, 3 cenários recuperados" in render_markdown(
        report
    )


def test_relatorio_sem_retry_fica_identico_ao_anterior():
    from evals.report import render_markdown

    report = _report(None)

    assert "infra_retry" not in report
    assert report["cost_usd"] == 1.0
    assert "reexecuções" not in render_markdown(report)


# ----------------------------------------------------------------- CLI


def _cli_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, script: dict[str, list[Any]]):
    from evals import __main__ as cli

    calls: list[tuple[list[str], int]] = []

    async def fake_run_all(
        scenarios: Any, environ: Any, concurrency: int = cli.CONCURRENCY
    ) -> dict[str, Any]:
        calls.append(([s.id for s in scenarios], concurrency))
        return {s.id: script[s.id].pop(0) if script.get(s.id) else _ok(s.id) for s in scenarios}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "RETRY_PAUSE_S", 0.0)
    return cli, calls


def test_cli_reexecuta_so_o_cenario_com_infra_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from evals.subsets import QUICK_SUBSET

    first_id = sorted(QUICK_SUBSET)[0]
    cli, calls = _cli_setup(monkeypatch, tmp_path, {first_id: [_infra(first_id)]})

    code = cli.main(["run", "--label", "r", "--subset", "quick"], environ={})

    assert code == 0
    assert calls[0][1] == cli.CONCURRENCY
    assert calls[1] == ([first_id], 2)
    assert len(calls) == 2
    report = next(tmp_path.glob("*-r.md")).read_text(encoding="utf-8")
    assert "1 rodadas, 1 cenários recuperados" in report


def test_cli_retry_infra_zero_nao_reexecuta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from evals.subsets import QUICK_SUBSET

    first_id = sorted(QUICK_SUBSET)[0]
    cli, calls = _cli_setup(monkeypatch, tmp_path, {first_id: [_infra(first_id)]})

    cli.main(["run", "--label", "z", "--subset", "quick", "--retry-infra", "0"], environ={})

    assert len(calls) == 1
    assert "reexecuções" not in next(tmp_path.glob("*-z.md")).read_text(encoding="utf-8")


def test_makefile_passa_retry_infra_por_padrao():
    makefile = (Path(__file__).resolve().parents[3] / "Makefile").read_text(encoding="utf-8")
    eval_lines = [
        line
        for line in makefile.splitlines()
        if "python -m evals run" in line
        # holdout é manual; eval-record e eval-ci (replay, ADR 0016) têm política própria
        and not any(alvo in line for alvo in ("holdout", "--record", "--label ci"))
    ]

    assert len(eval_lines) == 2
    assert all("--retry-infra 2" in line for line in eval_lines)
