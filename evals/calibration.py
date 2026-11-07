"""Calibração do juiz: amostra para rotulagem humana e concordância rótulo × juiz."""

import asyncio
import json
import random
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
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


DEFAULT_CONCURRENCY = 4

Progress = Callable[[int, int, str, bool], None]


async def calibrate(
    provider: LLMProvider,
    traces: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress: Progress | None = None,
) -> Calibration:
    """Julga as conversas rotuladas com concorrência limitada; a ordem dos rótulos é mantida.

    `on_progress(done, total, scenario_id, judged)` é chamado a cada conversa concluída.
    """
    by_id = {str(row["id"]): row for row in traces}
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(label: Mapping[str, Any]) -> int | None:
        nonlocal done
        scenario_id = str(label["id"])
        row = by_id.get(scenario_id)
        score: int | None = None
        if row is not None:
            async with gate:
                result = await judge_trace(provider, trace_from_row(row))
            score = None if result.score is None else result.score.overall
        done += 1
        if on_progress is not None:
            on_progress(done, len(labels), scenario_id, score is not None)
        return score

    scores = await asyncio.gather(*(one(label) for label in labels))
    pairs: list[tuple[str, int, int]] = []
    unjudged: list[str] = []
    for label, score in zip(labels, scores, strict=True):
        if score is None:
            unjudged.append(str(label["id"]))
        else:
            pairs.append((str(label["id"]), int(label["overall"]), score))
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
