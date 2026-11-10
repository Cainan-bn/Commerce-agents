"""Resiliência do provider de LLM (ADR 0017): circuit breaker, fallback e composição por ambiente.

Decoradores sobre o port `LLMProvider`: o retry continua dentro de cada adaptador e o breaker fica
por fora dele. O grafo não muda: quando tudo cai, recebe `LLMUnavailableError` e degrada para
humano. Logs citam só o nome do elo, nunca URL nem chave.
"""

import logging
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Literal, Protocol

from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import LLMProvider, LLMUnavailableError
from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env
from commerce_agents.infrastructure.llm.recorded import RecordingLLM
from commerce_agents.infrastructure.telemetry import CIRCUIT_OPENED, FALLBACK_USED

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
BuildProvider = Callable[[Mapping[str, str]], LLMProvider]
CircuitState = Literal["closed", "open", "half_open"]

PRIMARY_NAME = "primario"
FALLBACK_NAME = "secundario"
# Variáveis do primário que o secundário recebe de `LLM_FALLBACK_*` (nunca herdadas).
_PROVIDER_VARS = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MAX_RETRIES",
    "LLM_TIMEOUT_S",
)
_REQUIRED_FALLBACK_VARS = ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL")


class NamedLLM(LLMProvider, Protocol):
    """Elo da cadeia de fallback: um `LLMProvider` com nome (métricas, custo e motivos)."""

    name: str


def _tagged(result: LLMResult, name: str) -> LLMResult:
    return result if result.provider else result.model_copy(update={"provider": name})


class CircuitBreakerLLM:
    """Fechado → aberto → meio-aberto sobre um `LLMProvider` (ADR 0017).

    Só `LLMUnavailableError` conta como falha; `LLMBadRequestError` é erro do pedido e passa.
    """

    def __init__(
        self,
        inner: LLMProvider,
        *,
        name: str,
        failure_threshold: int = 5,
        window_s: float = 60.0,
        open_s: float = 30.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self.inner = inner
        self.name = name
        self._threshold = failure_threshold
        self._window_s = window_s
        self._open_s = open_s
        self._clock = clock
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None
        # Meio-aberto: só uma chamada de teste por vez (sem await entre checar e marcar).
        self._probing = False

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._open_s:
            return "half_open"
        return "open"

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        state = self.state
        if state == "open" or (state == "half_open" and self._probing):
            raise LLMUnavailableError(f"circuito aberto: {self.name}")
        probe = state == "half_open"
        self._probing = probe
        try:
            result = await self.inner.complete(messages, max_tokens=max_tokens)
        except LLMUnavailableError:
            self._on_failure(probe)
            raise
        finally:
            if probe:
                self._probing = False
        if probe:
            self._close()
        return _tagged(result, self.name)

    def _on_failure(self, probe: bool) -> None:
        now = self._clock()
        if probe:
            self._open(now)
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self._window_s:
            self._failures.popleft()
        if len(self._failures) >= self._threshold:
            self._open(now)

    def _open(self, now: float) -> None:
        self._opened_at = now
        self._failures.clear()
        CIRCUIT_OPENED.add(1, {"provider": self.name})
        logger.warning("llm: circuito aberto para %s por %.0fs", self.name, self._open_s)

    def _close(self) -> None:
        self._opened_at = None
        self._failures.clear()
        logger.info("llm: circuito fechado para %s", self.name)


class FallbackLLM:
    """Tenta os providers em ordem; passa ao próximo só em `LLMUnavailableError`."""

    def __init__(self, providers: Sequence[NamedLLM]) -> None:
        if not providers:
            raise ValueError("FallbackLLM exige ao menos um provider")
        self.providers = list(providers)

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        reasons: list[str] = []
        for provider in self.providers:
            try:
                result = await provider.complete(messages, max_tokens=max_tokens)
            except LLMUnavailableError as error:
                reasons.append(f"{provider.name}: {error}")
                continue
            if reasons:
                FALLBACK_USED.add(1, {"provider": provider.name})
                logger.warning("llm: respondido pelo fallback %s", provider.name)
            return _tagged(result, provider.name)
        raise LLMUnavailableError("todos os providers indisponíveis: " + "; ".join(reasons))


def _fallback_env(env: Mapping[str, str]) -> dict[str, str] | None:
    """Ambiente do secundário a partir de `LLM_FALLBACK_*`; `None` se não houver fallback."""
    present = [name for name in _REQUIRED_FALLBACK_VARS if env.get(name)]
    if not present:
        return None
    missing = [name for name in _REQUIRED_FALLBACK_VARS if not env.get(name)]
    if missing:
        raise ValueError(f"fallback incompleto: defina {', '.join(missing)}")
    secondary = {k: v for k, v in env.items() if k not in _PROVIDER_VARS}
    for var in _PROVIDER_VARS:
        value = env.get(var.replace("LLM_", "LLM_FALLBACK_", 1))
        if value:
            secondary[var] = value
    return secondary


def build_resilient_llm(
    env: Mapping[str, str],
    *,
    build_provider: BuildProvider = build_provider_from_env,
    clock: Clock = time.monotonic,
) -> LLMProvider:
    """Primário (`LLM_*`) no breaker; com `LLM_FALLBACK_*`, cadeia primário → secundário.

    Com secundário, o primário não repete (ADR 0019): a falha passa logo ao próximo elo e o
    breaker do primário abre em segundos; só o último elo da cadeia faz novas tentativas.
    Com `LLM_RECORD_TO`, cada adaptador ganha um gravador por dentro do breaker (ADR 0020):
    só respostas reais vão ao cassete da demonstração.
    """
    record_to = env.get("LLM_RECORD_TO")
    if record_to:
        if env.get("LLM_PROVIDER") == "recorded":
            raise ValueError("LLM_RECORD_TO não combina com LLM_PROVIDER=recorded")
        build_provider = _recording(build_provider, record_to)
    secondary_env = _fallback_env(env)
    if secondary_env is None:
        return CircuitBreakerLLM(build_provider(env), name=PRIMARY_NAME, clock=clock)
    primary = CircuitBreakerLLM(
        build_provider({**env, "LLM_MAX_RETRIES": "0"}), name=PRIMARY_NAME, clock=clock
    )
    secondary = CircuitBreakerLLM(build_provider(secondary_env), name=FALLBACK_NAME, clock=clock)
    return FallbackLLM([primary, secondary])


def _recording(build_provider: BuildProvider, path: str) -> BuildProvider:
    def build(env: Mapping[str, str]) -> LLMProvider:
        return RecordingLLM(build_provider(env), path)

    return build
