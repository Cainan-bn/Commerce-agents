"""Reexecução de cenários com erro de infraestrutura (janela de indisponibilidade do provider).

Só cenários com `infra_error` voltam a rodar: o resultado determinístico do agente nunca é
re-sorteado. Uma reexecução só substitui o trace quando termina sem erro de infraestrutura.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from data.eval_scenarios_schema import EvalScenario

from evals.trace import Trace

RETRY_CONCURRENCY = 2

RunBatch = Callable[[list[EvalScenario], int], Awaitable[dict[str, Trace]]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class InfraRetry:
    traces: dict[str, Trace]
    rounds: int
    recovered: int
    extra_cost_usd: float


async def retry_infra(
    scenarios: list[EvalScenario],
    traces: dict[str, Trace],
    run: RunBatch,
    *,
    rounds: int,
    pause_s: float,
    sleep: Sleep = asyncio.sleep,
) -> InfraRetry:
    final = dict(traces)
    extra = 0.0
    recovered = 0
    executed = 0
    for _ in range(rounds):
        pending = [s for s in scenarios if final[s.id].infra_error]
        if not pending:
            break
        await sleep(pause_s)
        executed += 1
        fresh = await run(pending, RETRY_CONCURRENCY)
        for scenario in pending:
            new, old = fresh[scenario.id], final[scenario.id]
            if new.infra_error is None:
                extra += old.cost_usd or 0.0
                final[scenario.id] = new
                recovered += 1
            else:
                extra += new.cost_usd or 0.0
    return InfraRetry(traces=final, rounds=executed, recovered=recovered, extra_cost_usd=extra)
