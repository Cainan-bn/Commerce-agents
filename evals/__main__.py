"""CLI: `python -m evals run|calibrate-export|calibrate` (ver `--help` de cada subcomando)."""

import argparse
import asyncio
import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml
from data.eval_scenarios_schema import EvalScenario

from evals.calibration import (
    calibrate,
    format_calibration,
    read_jsonl,
    sample_for_labeling,
    write_jsonl,
)
from evals.harness import build_real_deps, run_scenario
from evals.judge import JudgeResult, judge_scenario
from evals.metrics import aggregate, evaluate
from evals.report import build_report, build_trace_rows, write_report, write_traces
from evals.retry import retry_infra
from evals.subsets import QUICK_SUBSET
from evals.trace import Trace

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = REPO_ROOT / "data" / "eval_scenarios"
POLICIES_DIR = REPO_ROOT / "data" / "policies"
REPORTS_DIR = REPO_ROOT / "reports" / "eval"
CONCURRENCY = 4
LLM_TIMEOUT_S = 180.0
DEFAULT_RETRY_INFRA = 2
RETRY_PAUSE_S = 20.0


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"inteiro inválido: {raw!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("deve ser >= 1")
    return value


def _positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"número inválido: {raw!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("deve ser > 0")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="executa a suíte e grava o relatório")
    run.add_argument("--label", required=True)
    run.add_argument("--subset", choices=("all", "quick"), default="all")
    run.add_argument("--split", choices=("dev", "holdout"), default="dev")
    run.add_argument(
        "--retry-infra",
        type=int,
        default=DEFAULT_RETRY_INFRA,
        metavar="N",
        help="rodadas de reexecução só dos cenários com erro de infraestrutura (0 desliga)",
    )
    run.add_argument(
        "--judge", action="store_true", help="acrescenta o juiz LLM (sinal secundário)"
    )
    run.add_argument(
        "--concurrency",
        type=_positive_int,
        default=CONCURRENCY,
        metavar="N",
        help="cenários e chamadas ao LLM em paralelo (>= 1)",
    )
    run.add_argument(
        "--llm-timeout",
        type=_positive_float,
        default=LLM_TIMEOUT_S,
        metavar="S",
        help="timeout, em segundos, de cada chamada ao LLM (> 0)",
    )
    export = sub.add_parser("calibrate-export", help="amostra conversas para rotulagem humana")
    export.add_argument("--traces", type=Path, required=True)
    export.add_argument("--n", type=int, default=30)
    export.add_argument("--out", type=Path, required=True)
    calib = sub.add_parser("calibrate", help="concordância entre os rótulos humanos e o juiz")
    calib.add_argument("--traces", type=Path, required=True)
    calib.add_argument("--labels", type=Path, required=True)
    calib.add_argument("--label", required=True)
    return parser.parse_args(argv)


def check_split_allowed(split: str, *, environ: Mapping[str, str], repo_root: Path) -> None:
    """O holdout só roda com `EVAL_HOLDOUT_DIR` apontando para FORA do repositório."""
    if split != "holdout":
        return
    configured = environ.get("EVAL_HOLDOUT_DIR")
    if not configured:
        raise SystemExit("holdout recusado: defina EVAL_HOLDOUT_DIR (fora do repositório)")
    holdout = Path(configured).resolve()
    if holdout == repo_root.resolve() or repo_root.resolve() in holdout.parents:
        raise SystemExit("holdout recusado: EVAL_HOLDOUT_DIR não pode ficar dentro do repositório")


def load_scenarios(
    split: str, subset: str, *, environ: Mapping[str, str], dev_dir: Path = DEV_DIR
) -> list[EvalScenario]:
    directory = Path(environ["EVAL_HOLDOUT_DIR"]) if split == "holdout" else dev_dir
    scenarios = [
        EvalScenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.yaml"))
    ]
    scenarios = [s for s in scenarios if s.split == split]
    if subset == "quick":
        scenarios = [s for s in scenarios if s.id in QUICK_SUBSET]
    return scenarios


def _commit() -> str:
    try:
        out = subprocess.run(  # noqa: S603 - argv fixo, sem shell
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido"


def _corpus_version(policies_dir: Path = POLICIES_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(policies_dir.rglob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


async def _run_all(
    scenarios: list[EvalScenario], environ: Mapping[str, str], concurrency: int = CONCURRENCY
) -> dict[str, Trace]:
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env

    llm = build_provider_from_env(environ)
    gate = asyncio.Semaphore(concurrency)

    async def one(scenario: EvalScenario) -> tuple[str, Trace]:
        async with gate:
            # Um ambiente isolado (loja, tokens, checkpoint) por cenário.
            deps = build_real_deps(
                llm=llm,
                model=environ.get("LLM_MODEL", ""),
                llm_provider_name=environ.get("LLM_PROVIDER", ""),
            )
            return scenario.id, await run_scenario(scenario, deps)

    return dict(await asyncio.gather(*(one(s) for s in scenarios)))


async def _judge_all(
    scenarios: list[EvalScenario],
    traces: dict[str, Trace],
    environ: Mapping[str, str],
    concurrency: int = CONCURRENCY,
) -> dict[str, JudgeResult]:
    from commerce_agents.infrastructure.llm.openai_compatible import build_judge_provider_from_env

    provider = build_judge_provider_from_env(environ)
    gate = asyncio.Semaphore(concurrency)

    async def one(scenario: EvalScenario) -> tuple[str, JudgeResult]:
        async with gate:
            return scenario.id, await judge_scenario(provider, scenario, traces[scenario.id])

    return dict(await asyncio.gather(*(one(s) for s in scenarios)))


def _calibrate_export(args: argparse.Namespace) -> int:
    rows = sample_for_labeling(read_jsonl(args.traces), args.n)
    write_jsonl(rows, args.out)
    print(f"{len(rows)} conversas para rotular: {args.out}")  # noqa: T201
    return 0


def _print_progress(done: int, total: int, scenario_id: str, judged: bool) -> None:
    print(f"[{done}/{total}] {scenario_id} {'ok' if judged else 'sem nota'}", file=sys.stderr)  # noqa: T201


def _calibrate(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    from commerce_agents.infrastructure.llm.openai_compatible import build_judge_provider_from_env

    provider = build_judge_provider_from_env(environ)
    result = asyncio.run(
        calibrate(
            provider,
            read_jsonl(args.traces),
            read_jsonl(args.labels),
            concurrency=CONCURRENCY,
            on_progress=_print_progress,
        )
    )
    print(format_calibration(args.label, result))  # noqa: T201
    return 0  # medida, não gate


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    env = os.environ if environ is None else environ
    args = parse_args(argv)
    if args.command == "calibrate-export":
        return _calibrate_export(args)
    if args.command == "calibrate":
        return _calibrate(args, env)
    check_split_allowed(args.split, environ=env, repo_root=REPO_ROOT)
    scenarios = load_scenarios(args.split, args.subset, environ=env)
    env = {
        **env,
        "LLM_OPENCODE_MAX_CONCURRENCY": str(args.concurrency),
        "LLM_OPENCODE_TIMEOUT_S": str(args.llm_timeout),
    }
    started = clock()
    traces = asyncio.run(_run_all(scenarios, env, args.concurrency))
    agent_done = clock()
    retry = None
    if args.retry_infra > 0:
        retry = asyncio.run(
            retry_infra(
                scenarios,
                traces,
                lambda subset, concurrency: _run_all(
                    subset, env, min(concurrency, args.concurrency)
                ),
                rounds=args.retry_infra,
                pause_s=RETRY_PAUSE_S,
            )
        )
        traces = retry.traces
    retry_done = clock()
    by_id = {s.id: s for s in scenarios}
    results = [evaluate(traces[s.id], s) for s in scenarios]
    judge_started = clock()
    judged = (
        asyncio.run(_judge_all(scenarios, traces, env, args.concurrency)) if args.judge else None
    )
    finished = clock()
    timing = {
        "agent": agent_done - started,
        "retry": retry_done - agent_done,
        "judge": finished - judge_started,
        "total": finished - started,
    }
    report = build_report(
        label=args.label,
        commit=_commit(),
        corpus_version=_corpus_version(),
        models={"agent": env.get("LLM_MODEL", ""), "judge": env.get("LLM_JUDGE_MODEL", "")},
        temperature=0.0,
        aggregate=aggregate(results),
        results=results,
        scenarios=by_id,
        traces=traces,
        judge=judged,
        infra_retry=retry,
        timing=timing,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    paths = write_report(report, REPORTS_DIR, timestamp=stamp)
    write_traces(
        build_trace_rows(by_id, traces, judged),
        REPORTS_DIR,
        stem=f"{stamp}-{args.label}",
    )
    print(f"relatório: {paths[1]}")  # noqa: T201
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
