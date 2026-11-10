"""Provider pelo cliente `opencode run` (ADR 0015, adendo).

Subprocesso SEM shell: a mensagem inteira vai como UM argumento do argv. O stderr do processo
nunca entra em exceção nem em log (pode conter segredos).
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import LLMBadRequestError, LLMUnavailableError

__all__ = ["LLMBadRequestError", "LLMUnavailableError", "OpenCodeCliProvider", "default_runner"]

logger = logging.getLogger(__name__)

Runner = Callable[..., Awaitable[tuple[int, str, str]]]
Sleep = Callable[[float], Awaitable[None]]

_ROLES = {"system": "SISTEMA", "user": "USUARIO", "assistant": "ASSISTENTE"}
_BACKOFF_BASE_SECONDS = 2.0
_BACKOFF_CAP_SECONDS = 30.0


async def default_runner(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
    """Executa o argv sem shell; estourar o prazo mata o processo e levanta `TimeoutError`."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        raise
    return (
        process.returncode if process.returncode is not None else -1,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


@dataclass(frozen=True)
class _Parsed:
    text: str
    input_tokens: int
    output_tokens: int
    cost: float | None


class OpenCodeCliProvider:
    """Adaptador `LLMProvider` que delega ao `opencode run` com o agente `plain`."""

    def __init__(
        self,
        model: str,
        *,
        workdir: Path,
        agent: str = "plain",
        timeout: float = 180.0,
        max_concurrency: int = 4,
        max_retries: int = 2,
        runner: Runner = default_runner,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if "/" not in model:
            raise ValueError("o modelo do opencode deve ter a forma provedor/modelo")
        if not Path(workdir).is_dir():
            raise ValueError("workdir do opencode não existe")
        self.model = model
        self._workdir = Path(workdir)
        self._agent = agent
        self._timeout = timeout
        self._max_retries = max_retries
        self._runner = runner
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.last_cost_usd: float | None = None
        self.total_cost_usd = 0.0

    def __repr__(self) -> str:
        return f"OpenCodeCliProvider(model={self.model!r}, agent={self._agent!r})"

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        argv = [
            "opencode",
            "run",
            "--dir",
            str(self._workdir),
            "-m",
            self.model,
            "--agent",
            self._agent,
            "--format",
            "json",
            _serialize(messages),
        ]
        for attempt in range(self._max_retries + 1):
            reason = ""
            try:
                async with self._semaphore:
                    code, stdout, _stderr = await self._runner(argv, timeout=self._timeout)
            except TimeoutError:
                reason = "timeout"
            else:
                parsed = _parse(stdout) if code == 0 else None
                if parsed is not None:
                    return self._finish(parsed)
                reason = f"código {code}" if code != 0 else "saída sem texto utilizável"
            if attempt == self._max_retries:
                raise LLMUnavailableError(f"opencode indisponível ({reason})")
            logger.warning("opencode falhou (%s); nova tentativa", reason)
            await self._sleep(_backoff(attempt))
        raise AssertionError("inalcançável")  # pragma: no cover

    def _finish(self, parsed: _Parsed) -> LLMResult:
        self.last_cost_usd = parsed.cost
        if parsed.cost is not None:
            self.total_cost_usd += parsed.cost
        return LLMResult(
            content=parsed.text,
            model=self.model,
            input_tokens=parsed.input_tokens,
            output_tokens=parsed.output_tokens,
            cost_usd=parsed.cost,
        )


def _serialize(messages: list[LLMMessage]) -> str:
    return "\n\n".join(f"[{_ROLES.get(m.role, m.role.upper())}]\n{m.content}" for m in messages)


def _backoff(attempt: int) -> float:
    delay = min(_BACKOFF_BASE_SECONDS * float(2**attempt), _BACKOFF_CAP_SECONDS)
    jitter: float = random.uniform(0, delay / 2)  # não criptográfico
    return delay + jitter


def _parse(stdout: str) -> _Parsed | None:
    """Concatena eventos `text`; soma tokens e custo dos `step_finish`. None se inutilizável."""
    texts: list[str] = []
    input_tokens = output_tokens = 0
    cost: float | None = None
    for line in stdout.splitlines():
        event = _event(line)
        if event is None:
            continue
        kind = event.get("type")
        part = event.get("part") or {}
        if kind == "error":
            return None
        if kind == "text":
            texts.append(str(part.get("text", "")))
        elif kind == "step_finish":
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            input_tokens += (
                int(tokens.get("input", 0)) + int(cache.get("read", 0)) + int(cache.get("write", 0))
            )
            output_tokens += int(tokens.get("output", 0))
            if part.get("cost") is not None:
                cost = (cost or 0.0) + float(part["cost"])
    if not texts:
        return None
    return _Parsed("".join(texts), input_tokens, output_tokens, cost)


def _event(line: str) -> dict[str, Any] | None:
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None
