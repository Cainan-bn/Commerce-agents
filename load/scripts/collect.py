"""Coleta o resultado de um cenário de carga: k6, Prometheus, stub do LLM e CPU/memória.

Só lê e resume o que foi medido; nada é estimado. Uso: ver load/run.sh.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_GAP_S = 10.0  # sem 503 por 10 s depois da queda: o circuito parou de chamar o provider

_TURN = "conversation_turn_duration_seconds"


def _quantile(q: float, histogram: str) -> str:
    return f"histogram_quantile({q}, sum by (le) (increase({histogram}_bucket[{{w}}])))"


def _mean(histogram: str) -> str:
    return f"sum(increase({histogram}_sum[{{w}}])) / sum(increase({histogram}_count[{{w}}]))"


# Percentis do Prometheus dependem dos buckets do histograma (TASK-09-03e).
QUERIES = {
    "turnos": f"sum(increase({_TURN}_count[{{w}}]))",
    "turno_p50_s": _quantile(0.5, _TURN),
    "turno_p95_s": _quantile(0.95, _TURN),
    "turno_p99_s": _quantile(0.99, _TURN),
    "turno_medio_s": _mean(_TURN),
    "llm_p95_s": _quantile(0.95, "llm_duration_seconds"),
    "llm_medio_s": _mean("llm_duration_seconds"),
    "ferramenta_p95_s": _quantile(0.95, "tool_duration_seconds"),
    "ferramenta_media_s": _mean("tool_duration_seconds"),
    "custo_medio_turno_usd": _mean("conversation_turn_cost_USD"),
    "circuito_aberturas": "sum(increase(llm_circuit_opened_total[{w}]))",
    "fallback_usado": "sum(increase(llm_fallback_used_total[{w}]))",
}
GROUPED = {
    "llm_chamadas_por_resultado": ("sum by (outcome) (increase(llm_calls_total[{w}]))", "outcome"),
    "handoffs_por_motivo": ("sum by (reason) (increase(handoff_requested_total[{w}]))", "reason"),
}


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - URL local do operador
        return json.load(response)


def prometheus(base: str, start: int, end: int) -> dict[str, Any]:
    now = _get(f"{base}/api/v1/query?query=time()")["data"]["result"][1]
    window = f"{max(60, int(float(now)) - start)}s"

    def query(expr: str) -> list[Any]:
        url = f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": expr.format(w=window)})
        return list(_get(url)["data"]["result"])

    result: dict[str, Any] = {"janela": window, "fim_da_carga": end}
    for name, expr in QUERIES.items():
        rows = query(expr)
        value = float(rows[0]["value"][1]) if rows else None
        result[name] = None if value is None or value != value else round(value, 6)
    for name, (expr, label) in GROUPED.items():
        result[name] = {
            row["metric"].get(label, "?"): round(float(row["value"][1]), 3) for row in query(expr)
        }
    return result


def stub(base: str) -> dict[str, Any]:
    stats = _get(f"{base}/admin/stats")
    downs = [ts for ts, down in stats["down_changes"] if down]
    rejected = sorted(stats["rejected_at"])
    result: dict[str, Any] = {"contagens": stats["counts"], "trocas_de_modo": stats["down_changes"]}
    if downs and rejected:
        went_down = downs[0]
        burst = [ts for ts in rejected if ts >= went_down]
        open_at = burst[0] if burst else None
        for previous, current in zip(burst, burst[1:], strict=False):
            if current - previous >= _GAP_S:
                open_at = previous
                break
        else:
            open_at = burst[-1] if burst else None
        result["caiu_em"] = went_down
        result["ultimo_503_antes_da_pausa_s"] = (
            round(open_at - went_down, 2) if open_at is not None else None
        )
        result["chamadas_503"] = len(burst)
    return result


def resources(path: Path, names: list[str]) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []
    summary: dict[str, Any] = {}
    for name in names:
        cpu = [float(r["cpu_percent"]) for r in rows if r["name"] == name]
        rss = [int(r["rss_kb"]) for r in rows if r["name"] == name]
        if cpu:
            summary[name] = {
                "amostras": len(cpu),
                "cpu_medio_pct": round(statistics.fmean(cpu), 1),
                "cpu_max_pct": max(cpu),
                "rss_max_mb": round(max(rss) / 1024, 1),
            }
    return summary


def containers(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []
    summary: dict[str, Any] = {}
    for row in rows:
        entry = summary.setdefault(row["container"], {"cpu": [], "mem": row["mem_usage"]})
        try:
            entry["cpu"].append(float(row["cpu_percent"]))
        except ValueError:
            continue
        entry["mem"] = row["mem_usage"]
    return {
        name: {
            "cpu_medio_pct": round(statistics.fmean(v["cpu"]), 1) if v["cpu"] else None,
            "cpu_max_pct": max(v["cpu"]) if v["cpu"] else None,
            "mem_final": v["mem"],
        }
        for name, v in summary.items()
    }


def k6(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    metrics = json.loads(path.read_text(encoding="utf-8"))["metrics"]
    keep = {
        "http_req_duration{name:webhook}",
        "http_reqs",
        "http_req_failed",
        "first_response_ms",
        "no_reply",
        "api_5xx",
        "replied",
        "iterations",
        "checks",
        "dropped_iterations",
    }
    return {name: values for name, values in metrics.items() if name in keep}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prometheus", required=True)
    parser.add_argument("--stub", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--k6-summary", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--docker", type=Path, required=True)
    parser.add_argument("--names", nargs="+", default=[])
    args = parser.parse_args()
    result = {
        "duracao_s": args.end - args.start,
        "k6": k6(args.k6_summary),
        "prometheus": prometheus(args.prometheus, args.start, args.end),
        "stub": stub(args.stub),
        "processos": resources(args.resources, args.names),
        "containers": containers(args.docker),
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
