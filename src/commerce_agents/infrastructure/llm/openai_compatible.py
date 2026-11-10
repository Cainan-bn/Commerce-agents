"""Provider para o protocolo `POST {base_url}/chat/completions` (ADR 0015).

A chave vem só do ambiente e nunca aparece em erro, `repr` nem log.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import (
    LLMBadRequestError,
    LLMProvider,
    LLMUnavailableError,
)
from commerce_agents.infrastructure.llm.pricing import PriceTable, estimate_cost_usd, load_pricing

__all__ = [
    "LLMBadRequestError",
    "LLMUnavailableError",
    "OpenAICompatibleProvider",
    "build_judge_provider_from_env",
    "build_provider_from_env",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 30.0

_REPO_ROOT = Path(__file__).resolve().parents[4]

Sleep = Callable[[float], Awaitable[None]]


class OpenAICompatibleProvider:
    """Adaptador `LLMProvider` para OpenAI e compatíveis, com retry e backoff com jitter."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        pricing: PriceTable | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("LLM_API_KEY é obrigatório para o provider openai-compatible")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self.model = model
        self._temperature = temperature
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._sleep = sleep
        self._pricing = load_pricing() if pricing is None else pricing

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider(url={self._url!r}, model={self.model!r})"

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        payload = {
            "model": self.model,
            "temperature": self._temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        for attempt in range(self._max_retries + 1):
            retry_after, failure = await self._attempt(payload)
            if isinstance(failure, LLMResult):
                return failure
            if attempt == self._max_retries:
                raise LLMUnavailableError(failure)
            await self._sleep(retry_after if retry_after is not None else _backoff(attempt))
        raise AssertionError("inalcançável")  # pragma: no cover

    async def _attempt(self, payload: dict[str, Any]) -> tuple[float | None, LLMResult | str]:
        """Uma tentativa: devolve o resultado, ou (Retry-After, motivo) quando repetível."""
        try:
            response = await self._client.post(
                self._url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as error:
            return None, f"falha de rede ({type(error).__name__})"
        status = response.status_code
        if status == 429 or status >= 500:
            return _retry_after(response), f"provider respondeu {status}"
        if status >= 400:
            raise LLMBadRequestError(f"provider recusou a requisição ({status})")
        parsed = self._parse(response)
        if parsed is None:
            return None, "resposta sem conteúdo utilizável"
        return None, parsed

    def _parse(self, response: httpx.Response) -> LLMResult | None:
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
            model = str(body.get("model") or self.model)
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            return LLMResult(
                content=str(content),
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=estimate_cost_usd(model, input_tokens, output_tokens, self._pricing),
            )
        except (ValueError, KeyError, IndexError, TypeError):
            return None


def _backoff(attempt: int) -> float:
    delay = min(_BACKOFF_BASE_SECONDS * float(2**attempt), _BACKOFF_CAP_SECONDS)
    jitter: float = random.uniform(0, delay / 2)  # não criptográfico
    return delay + jitter


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["Retry-After"]))
    except (KeyError, ValueError):
        return None


def _build(env: Mapping[str, str], model_var: str) -> LLMProvider:
    model = env.get(model_var, "")
    provider = env.get("LLM_PROVIDER") or (
        "openai-compatible" if env.get("LLM_API_KEY") else "opencode-cli"
    )
    if provider == "opencode-cli":
        from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

        if not model:
            raise ValueError(f"{model_var} é obrigatório")
        return OpenCodeCliProvider(
            model,
            workdir=_opencode_workdir(env),
            timeout=_env_number(env, "LLM_OPENCODE_TIMEOUT_S", float, 180.0),
            max_concurrency=int(_env_number(env, "LLM_OPENCODE_MAX_CONCURRENCY", int, 4)),
        )
    if provider == "openai-compatible":
        if not env.get("LLM_API_KEY"):
            raise ValueError("LLM_API_KEY é obrigatório com LLM_PROVIDER=openai-compatible")
        if not model:
            raise ValueError(f"{model_var} é obrigatório")
        return OpenAICompatibleProvider(
            env.get("LLM_BASE_URL") or DEFAULT_BASE_URL, env["LLM_API_KEY"], model
        )
    raise ValueError(f"LLM_PROVIDER inválido: {provider!r} (use opencode-cli ou openai-compatible)")


def _env_number(
    env: Mapping[str, str], name: str, parse: Callable[[str], float], default: float
) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = parse(raw)
    except ValueError:
        raise ValueError(f"{name} inválido: {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} deve ser > 0: {raw!r}")
    return value


def _opencode_workdir(env: Mapping[str, str]) -> Path:
    configured = env.get("LLM_WORKDIR")
    return Path(configured) if configured else _REPO_ROOT / "evals" / "opencode"


def build_provider_from_env(env: Mapping[str, str]) -> LLMProvider:
    """Provider do agente e do roteador (`LLM_MODEL`)."""
    return _build(env, "LLM_MODEL")


def build_judge_provider_from_env(env: Mapping[str, str]) -> LLMProvider:
    """Provider do juiz (`LLM_JUDGE_MODEL`), idealmente de outra família que o do agente."""
    return _build(env, "LLM_JUDGE_MODEL")
