"""Calibração do juiz: amostra para rotulagem humana e concordância rótulo × juiz."""

import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from commerce_agents.application.ports.llm import LLMProvider
from evals.judge import agreement, judge_trace
from evals.trace import ToolCallRecord, Trace, TurnRecord

SEED = 20260607
TOLERANCE = 1


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def sample_for_labeling(rows: Sequence[Mapping[str, Any]], n: int) -> list[dict[str, Any]]:
    """Amostra determinística de conversas resolvidas, em rodízio entre as categorias.

    Sai só o que o rotulador pode ver: sem nota do juiz e sem `expected`.
    """
    by_category: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: str(r["id"])):
        if row.get("outcome") == "resolved":
            by_category[str(row["category"])].append(row)
    rng = random.Random(SEED)  # noqa: S311 - amostragem reprodutível, não criptográfica
    queues = {name: rng.sample(items, len(items)) for name, items in sorted(by_category.items())}
    picked: list[Mapping[str, Any]] = []
    while len(picked) < n and any(queues.values()):
        for queue in queues.values():
            if queue and len(picked) < n:
                picked.append(queue.pop())
    return [
        {
            "id": row["id"],
            "category": row["category"],
            "conversation": [{"user": t["user_text"], "agent": t["reply"]} for t in row["turns"]],
            "tools": [c["name"] for c in row["tool_calls"]],
        }
        for row in picked
    ]


def write_jsonl(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def trace_from_row(row: Mapping[str, Any]) -> Trace:
    return Trace(
        scenario_id=str(row["id"]),
        turns=[
            TurnRecord(
                user_text=t["user_text"],
                reply=t["reply"],
                agent=t["agent"],
                intent=t["intent"],
                confidence=0.0,
            )
            for t in row["turns"]
        ],
        tool_calls=[
            ToolCallRecord(name=c["name"], ok=c["ok"], error_code=c["error_code"])
            for c in row["tool_calls"]
        ],
        policy_citations=list(row["policy_citations"]),
        infra_error=row.get("infra_error"),
    )


@dataclass(frozen=True)
class Calibration:
    pairs: list[tuple[str, int, int]]  # (id, rótulo humano, nota do juiz)
    unjudged: list[str]

    @property
    def agreement(self) -> float | None:
        return agreement([(a, b) for _, a, b in self.pairs], TOLERANCE) if self.pairs else None

    @property
    def disagreements(self) -> list[tuple[str, int, int]]:
        return [p for p in self.pairs if abs(p[1] - p[2]) > TOLERANCE]


async def calibrate(
    provider: LLMProvider,
    traces: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
) -> Calibration:
    by_id = {str(row["id"]): row for row in traces}
    pairs: list[tuple[str, int, int]] = []
    unjudged: list[str] = []
    for label in labels:
        scenario_id = str(label["id"])
        row = by_id.get(scenario_id)
        result = None if row is None else await judge_trace(provider, trace_from_row(row))
        if result is None or result.score is None:
            unjudged.append(scenario_id)
            continue
        pairs.append((scenario_id, int(label["overall"]), result.score.overall))
    return Calibration(pairs=pairs, unjudged=unjudged)


def format_calibration(name: str, result: Calibration) -> str:
    rate = result.agreement
    lines = [
        f"calibração do juiz — {name}",
        f"pares: {len(result.pairs)}; sem nota do juiz: {len(result.unjudged)}",
        f"concordância ±{TOLERANCE}: " + ("n/d" if rate is None else f"{rate * 100:.1f}%"),
    ]
    lines += [
        f"discordância: {sid} rótulo={human} juiz={judged}"
        for sid, human, judged in result.disagreements
    ]
    return "\n".join(lines)
