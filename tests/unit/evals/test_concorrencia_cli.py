"""CLI de avaliação: `--concurrency` e `--llm-timeout` (parse, validação e propagação)."""

from pathlib import Path
from typing import Any

import pytest

from tests.fakes.traces import trace, turn

pytestmark = pytest.mark.unit


def _cli():  # type: ignore[no-untyped-def]
    from evals import __main__ as cli

    return cli


def test_concorrencia_e_timeout_tem_defaults_4_e_180():
    args = _cli().parse_args(["run", "--label", "x"])

    assert args.concurrency == 4
    assert args.llm_timeout == 180


def test_concorrencia_e_timeout_aceitam_valores_explicitos():
    args = _cli().parse_args(["run", "--label", "x", "--concurrency", "7", "--llm-timeout", "45.5"])

    assert args.concurrency == 7
    assert args.llm_timeout == 45.5


@pytest.mark.parametrize("valor", ["0", "-1", "muitos"])
def test_concorrencia_invalida_e_erro_do_argparse(valor: str, capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as refused:
        _cli().parse_args(["run", "--label", "x", "--concurrency", valor])

    assert refused.value.code == 2
    assert "argument --concurrency" in capsys.readouterr().err


@pytest.mark.parametrize("valor", ["0", "-5", "rapido"])
def test_llm_timeout_invalido_e_erro_do_argparse(valor: str, capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as refused:
        _cli().parse_args(["run", "--label", "x", "--llm-timeout", valor])

    assert refused.value.code == 2
    assert "argument --llm-timeout" in capsys.readouterr().err


def test_main_repassa_concorrencia_e_timeout_ao_run_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    cli = _cli()
    chamadas: list[dict[str, Any]] = []

    async def fake_run_all(scenarios: Any, environ: Any, concurrency: int = 4) -> dict[str, Any]:
        chamadas.append({"concurrency": concurrency, "environ": dict(environ)})
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(
        [
            "run",
            "--label",
            "fake",
            "--subset",
            "quick",
            "--concurrency",
            "3",
            "--llm-timeout",
            "45",
        ],
        environ={"LLM_MODEL": "m"},
    )

    assert chamadas[0]["concurrency"] == 3
    assert chamadas[0]["environ"]["LLM_OPENCODE_MAX_CONCURRENCY"] == "3"
    assert chamadas[0]["environ"]["LLM_OPENCODE_TIMEOUT_S"] == "45.0"
    assert chamadas[0]["environ"]["LLM_MODEL"] == "m"


def test_main_padrao_usa_concorrencia_4_e_timeout_180(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    cli = _cli()
    chamadas: list[dict[str, Any]] = []

    async def fake_run_all(scenarios: Any, environ: Any, concurrency: int = 4) -> dict[str, Any]:
        chamadas.append({"concurrency": concurrency, "environ": dict(environ)})
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(["run", "--label", "fake", "--subset", "quick"], environ={})

    assert chamadas[0]["concurrency"] == 4
    assert chamadas[0]["environ"]["LLM_OPENCODE_MAX_CONCURRENCY"] == "4"
    assert chamadas[0]["environ"]["LLM_OPENCODE_TIMEOUT_S"] == "180.0"


def test_main_repassa_concorrencia_ao_juiz(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _cli()
    concorrencia_do_juiz: list[int] = []

    async def fake_run_all(scenarios: Any, environ: Any, concurrency: int = 4) -> dict[str, Any]:
        return {s.id: trace(s.id, turns=[turn()]) for s in scenarios}

    async def fake_judge_all(
        scenarios: Any, traces: Any, environ: Any, concurrency: int = 4
    ) -> dict[str, Any]:
        concorrencia_do_juiz.append(concurrency)
        return {}

    monkeypatch.setattr(cli, "_run_all", fake_run_all)
    monkeypatch.setattr(cli, "_judge_all", fake_judge_all)
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)

    cli.main(
        ["run", "--label", "fake", "--subset", "quick", "--judge", "--concurrency", "2"],
        environ={},
    )

    assert concorrencia_do_juiz == [2]
