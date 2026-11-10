"""Custo por chamada de LLM (Fase 09): `LLMResult.cost_usd`, `None` quando desconhecido.

Contrato fixado:
- `LLMResult.cost_usd: float | None = None`; nunca um 0 inventado;
- `OpenCodeCliProvider`: o custo do `step_finish` daquela chamada;
- `OpenAICompatibleProvider(..., pricing=<tabela>)`: custo pela tabela do modelo da resposta,
  `None` fora dela; sem `pricing`, usa `load_pricing()` (hoje vazia);
- `CircuitBreakerLLM` e `FallbackLLM` preservam `cost_usd` e `provider` do resultado.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.clock import FakeMonotonic

pytestmark = pytest.mark.unit

MESSAGES = [LLMMessage(role="system", content="sistema"), LLMMessage(role="user", content="oi")]
TABLE = {"modelo-servidor": {"input_per_million_usd": 1.0, "output_per_million_usd": 2.0}}


# ----------------------------------------------------------------- DTO


def test_cost_usd_padrao_e_none():
    result = LLMResult(content="x", model="m", input_tokens=1, output_tokens=1)

    assert result.cost_usd is None


def test_cost_usd_aceita_valor_conhecido():
    result = LLMResult(content="x", model="m", input_tokens=1, output_tokens=1, cost_usd=0.0125)

    assert result.cost_usd == pytest.approx(0.0125)


# ----------------------------------------------------------------- opencode


def _opencode_stdout(text: str, cost: float | None) -> str:
    part: dict[str, Any] = {"type": "step-finish", "tokens": {"input": 3, "output": 2}}
    if cost is not None:
        part["cost"] = cost
    lines = [
        json.dumps({"type": "text", "part": {"type": "text", "text": text}}),
        json.dumps({"type": "step_finish", "part": part}),
    ]
    return "\n".join(lines) + "\n"


def _opencode(outputs: list[str], workdir: Path) -> Any:
    from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

    queue = list(outputs)

    async def runner(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
        return 0, queue.pop(0), ""

    async def no_sleep(_: float) -> None:
        return None

    return OpenCodeCliProvider("opencode-go/modelo", workdir=workdir, runner=runner, sleep=no_sleep)


async def test_opencode_cada_resultado_traz_o_custo_da_propria_chamada(tmp_path: Path):
    provider = _opencode([_opencode_stdout("a", 0.001), _opencode_stdout("b", 0.002)], tmp_path)

    first = await provider.complete(MESSAGES, max_tokens=64)
    second = await provider.complete(MESSAGES, max_tokens=64)

    assert first.cost_usd == pytest.approx(0.001)
    assert second.cost_usd == pytest.approx(0.002)


async def test_opencode_sem_custo_no_step_finish_devolve_none(tmp_path: Path):
    provider = _opencode([_opencode_stdout("a", None)], tmp_path)

    result = await provider.complete(MESSAGES, max_tokens=64)

    assert result.cost_usd is None


# ----------------------------------------------------------------- openai-compatible


def _openai(model_in_body: str, **options: Any) -> Any:
    from commerce_agents.infrastructure.llm.openai_compatible import OpenAICompatibleProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": model_in_body,
                "choices": [{"message": {"role": "assistant", "content": "Olá"}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
            },
        )

    async def no_sleep(_: float) -> None:
        return None

    return OpenAICompatibleProvider(
        "https://provedor.example/v1",
        "chave-de-teste",  # pragma: allowlist secret
        "modelo-configurado",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=no_sleep,
        **options,
    )


async def test_openai_compativel_custo_pela_tabela_quando_o_modelo_esta_nela():
    result = await _openai("modelo-servidor", pricing=TABLE).complete(MESSAGES, max_tokens=8)

    assert result.cost_usd == pytest.approx(1.0 + 1.0)


async def test_openai_compativel_modelo_fora_da_tabela_e_none():
    result = await _openai("outro-modelo", pricing=TABLE).complete(MESSAGES, max_tokens=8)

    assert result.cost_usd is None


async def test_openai_compativel_tabela_padrao_vazia_nao_inventa_custo():
    result = await _openai("modelo-servidor").complete(MESSAGES, max_tokens=8)

    assert result.cost_usd is None


# ----------------------------------------------------------------- resiliência


class _Costed:
    def __init__(self, name: str, outcome: LLMResult | Exception) -> None:
        self.name = name
        self.outcome = outcome

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _result(cost: float | None, provider: str | None = None) -> LLMResult:
    return LLMResult(
        content="ok",
        model="m",
        input_tokens=1,
        output_tokens=1,
        provider=provider,
        cost_usd=cost,
    )


async def test_breaker_preserva_custo_e_provider():
    from commerce_agents.infrastructure.llm.resilience import CircuitBreakerLLM

    breaker = CircuitBreakerLLM(
        _Costed("x", _result(0.03, provider="interno")), name="primario", clock=FakeMonotonic()
    )

    result = await breaker.complete(MESSAGES, max_tokens=8)

    assert result.cost_usd == pytest.approx(0.03)
    assert result.provider == "interno"


async def test_fallback_preserva_o_custo_de_quem_respondeu():
    from commerce_agents.infrastructure.llm.resilience import FallbackLLM

    fallback = FallbackLLM(
        [
            _Costed("primario", LLMUnavailableError("fora do ar")),
            _Costed("secundario", _result(0.004)),
        ]
    )

    result = await fallback.complete(MESSAGES, max_tokens=8)

    assert result.cost_usd == pytest.approx(0.004)
    assert result.provider == "secundario"


async def test_fallback_preserva_custo_desconhecido_como_none():
    from commerce_agents.infrastructure.llm.resilience import FallbackLLM

    result = await FallbackLLM([_Costed("primario", _result(None))]).complete(
        MESSAGES, max_tokens=8
    )

    assert result.cost_usd is None
    assert result.provider == "primario"
