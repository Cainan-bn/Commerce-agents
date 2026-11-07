"""Relatório de avaliação: JSON + Markdown e comparação antes × depois (evals.md)."""

import json
from pathlib import Path
from typing import Any

from data.eval_scenarios_schema import EvalScenario

from evals.metrics import Aggregate, ScenarioResult
from evals.trace import Trace

_EXCERPT_CHARS = 200


def failure_excerpt(result: ScenarioResult, trace: Trace) -> str:
    failed = [name for name, ok in result.metrics.items() if not ok]
    reply = trace.turns[-1].reply[:_EXCERPT_CHARS] if trace.turns else ""
    return f"falhou: {', '.join(failed)}; resposta: {reply!r}"


def build_report(
    *,
    label: str,
    commit: str,
    corpus_version: str,
    models: dict[str, str],
    temperature: float,
    aggregate: Aggregate,
    results: list[ScenarioResult],
    scenarios: dict[str, EvalScenario],
    traces: dict[str, Trace],
) -> dict[str, Any]:
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    entries: list[dict[str, Any]] = []
    for result in results:
        entry: dict[str, Any] = {
            "id": result.scenario_id,
            "category": result.category,
            "scenario_pass": result.scenario_pass,
            "metrics": result.metrics,
            "tokens": result.tokens,
            "latency_p50_ms": result.latency_p50_ms,
            "latency_p95_ms": result.latency_p95_ms,
        }
        trace = traces[result.scenario_id]
        if result.infra_error:
            entry["infra_error"] = trace.infra_error
        elif not result.scenario_pass:
            entry["failure_excerpt"] = failure_excerpt(result, trace)
        entries.append(entry)
    return {
        "label": label,
        "commit": commit,
        "corpus_version": corpus_version,
        "models": models,
        "temperature": temperature,
        "cost_usd": sum(costs) if costs else None,
        "total": aggregate.total,
        "infra_errors": aggregate.infra_errors,
        "rates": aggregate.rates,
        "by_category": {name: agg.rates for name, agg in aggregate.by_category.items()},
        "scenarios": entries,
    }


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    models = report["models"]
    lines = [
        f"# Avaliação — {report['label']}",
        "",
        f"- commit: `{report['commit']}`",
        f"- corpus: `{report['corpus_version']}`",
        f"- modelo do agente: `{models.get('agent', '')}`; juiz: `{models.get('judge', '')}`",
        f"- temperatura: {report['temperature']}",
        f"- custo (USD): {report['cost_usd']}",
        f"- erros de infraestrutura: {report['infra_errors']}",
        "",
        "## Taxas por métrica",
        "",
        *_table(["métrica", "taxa"], [[k, _percent(v)] for k, v in report["rates"].items()]),
        "",
        "## Por categoria",
        "",
    ]
    categories = report["by_category"]
    metric_names = sorted({name for rates in categories.values() for name in rates})
    lines += _table(
        ["categoria", *metric_names],
        [
            [category, *[_percent(rates[name]) if name in rates else "-" for name in metric_names]]
            for category, rates in categories.items()
        ],
    )
    failures = [s for s in report["scenarios"] if s.get("failure_excerpt") or s.get("infra_error")]
    lines += ["", "## Falhas", ""]
    lines += [f"- **{s['id']}** ({s['category']}): {_why(s)}" for s in failures] or ["Nenhuma."]
    return "\n".join(lines) + "\n"


def _why(entry: dict[str, Any]) -> str:
    return str(entry.get("failure_excerpt") or f"infra: {entry.get('infra_error')}")


def write_report(report: dict[str, Any], out_dir: Path, *, timestamp: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{timestamp}-{report['label']}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return [json_path, md_path]


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[str]]:
    """Cenários que passaram a passar (`improved`) ou a falhar (`worsened`)."""
    was = {s["id"]: s["scenario_pass"] for s in before["scenarios"]}
    improved: list[str] = []
    worsened: list[str] = []
    for scenario in after["scenarios"]:
        previous = was.get(scenario["id"])
        if previous is None or previous == scenario["scenario_pass"]:
            continue
        (improved if scenario["scenario_pass"] else worsened).append(scenario["id"])
    return {"improved": improved, "worsened": worsened}
