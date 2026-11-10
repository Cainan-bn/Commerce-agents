"""Circuit breaker e fallback do provider de LLM (ADR 0017), com relógio falso e sem sleeps.

Contrato fixado (`commerce_agents.infrastructure.llm.resilience`):
- `CircuitBreakerLLM(inner, *, name, failure_threshold=5, window_s=60, open_s=30, clock)`:
  `clock` é monotônico em segundos (`Callable[[], float]`); expõe `name`, `inner` e `state`
  ("closed", "open" ou "half_open"). Aberto, levanta `LLMUnavailableError` com
  "circuito aberto" e o `name`, sem chamar o `inner`. No meio-aberto só uma chamada vai ao
  `inner`; as concorrentes falham na hora como circuito aberto.
- `FallbackLLM(providers)`: cada provider expõe `name`; o `LLMResult` devolvido leva
  `provider=<name>` de quem respondeu (campo opcional `LLMResult.provider: str | None = None`).
"""

import asyncio
from typing import Any

import pytest

from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import LLMBadRequestError, LLMUnavailableError
from tests.fakes.clock import FakeMonotonic
from tests.fakes.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.unit

MESSAGES = [LLMMessage(role="system", content="sistema"), LLMMessage(role="user", content="oi")]


def _resilience() -> Any:
    from commerce_agents.infrastructure.llm import resilience

    return resilience


def _breaker(
    inner: Any,
    clock: FakeMonotonic,
    *,
    name: str = "primario",
    failure_threshold: int = 3,
    window_s: float = 60.0,
    open_s: float = 30.0,
) -> Any:
    return _resilience().CircuitBreakerLLM(
        inner,
        name=name,
        failure_threshold=failure_threshold,
        window_s=window_s,
        open_s=open_s,
        clock=clock,
    )


def _down(n: int, reason: str = "provider fora do ar") -> list[str | Exception]:
    return [LLMUnavailableError(reason) for _ in range(n)]


async def _complete(provider: Any) -> LLMResult:
    result: LLMResult = await provider.complete(MESSAGES, max_tokens=64)
    return result


async def _fail(provider: Any, error: type[Exception] = LLMUnavailableError) -> str:
    with pytest.raises(error) as raised:
        await _complete(provider)
    return str(raised.value)


class NamedLLM(ScriptedLLM):
    """`ScriptedLLM` com `name`, como os elos da cadeia de fallback."""

    def __init__(self, name: str, responses: list[str | Exception]) -> None:
        super().__init__(responses, model=f"modelo-{name}")
        self.name = name


class GatedLLM:
    """Falha as `fail_first` primeiras chamadas; depois só responde quando o teste libera."""

    def __init__(self, *, fail_first: int = 0) -> None:
        self.fail_first = fail_first
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise LLMUnavailableError("provider fora do ar")
        self.entered.set()
        await self.release.wait()
        return LLMResult(content="ok", model="gated", input_tokens=1, output_tokens=1)


# ----------------------------------------------------------------------------- fechado


async def test_fechado_repassa_mensagens_e_max_tokens_ao_inner():
    inner = ScriptedLLM(["resposta"])
    breaker = _breaker(inner, FakeMonotonic())

    result = await _complete(breaker)

    assert result.content == "resposta"
    assert inner.calls == [MESSAGES]
    assert breaker.state == "closed"
    assert breaker.name == "primario"
    assert breaker.inner is inner


async def test_abre_apos_failure_threshold_falhas_dentro_da_janela():
    clock = FakeMonotonic()
    inner = ScriptedLLM(_down(3))
    breaker = _breaker(inner, clock, failure_threshold=3, window_s=60)

    for _ in range(3):
        assert "provider fora do ar" in await _fail(breaker)
        clock.advance(10)

    assert breaker.state == "open"
    assert len(inner.calls) == 3


async def test_falhas_fora_da_janela_nao_somam():
    clock = FakeMonotonic()
    inner = ScriptedLLM([*_down(3), "voltou"])
    breaker = _breaker(inner, clock, failure_threshold=3, window_s=60)

    await _fail(breaker)
    clock.advance(61)
    await _fail(breaker)
    await _fail(breaker)

    assert breaker.state == "closed"
    assert (await _complete(breaker)).content == "voltou"
    assert len(inner.calls) == 4


async def test_aberto_falha_na_hora_citando_circuito_aberto_e_o_nome_sem_chamar_o_inner():
    clock = FakeMonotonic()
    inner = ScriptedLLM(_down(2))
    breaker = _breaker(inner, clock, name="opencode-primario", failure_threshold=2)
    await _fail(breaker)
    await _fail(breaker)

    for _ in range(5):
        message = await _fail(breaker)
        assert "circuito aberto" in message
        assert "opencode-primario" in message

    assert len(inner.calls) == 2


async def test_padroes_do_adr_cinco_falhas_em_60s_e_aberto_por_30s():
    clock = FakeMonotonic()
    inner = ScriptedLLM([*_down(5), "voltou"])
    breaker = _resilience().CircuitBreakerLLM(inner, name="primario", clock=clock)

    for _ in range(4):
        await _fail(breaker)
        clock.advance(14)
    assert breaker.state == "closed"
    await _fail(breaker)
    assert breaker.state == "open"

    clock.advance(29.9)
    assert "circuito aberto" in await _fail(breaker)
    clock.advance(0.1)
    assert (await _complete(breaker)).content == "voltou"
    assert len(inner.calls) == 6


# ------------------------------------------------------------------------- meio-aberto


async def test_apos_open_s_meio_aberto_deixa_passar_uma_e_sucesso_fecha_e_zera_o_contador():
    clock = FakeMonotonic()
    inner = ScriptedLLM([*_down(3), "voltou", *_down(2), "segue"])
    breaker = _breaker(inner, clock, failure_threshold=3, open_s=30)
    for _ in range(3):
        await _fail(breaker)

    clock.advance(30)
    assert breaker.state == "half_open"
    assert (await _complete(breaker)).content == "voltou"
    assert breaker.state == "closed"

    await _fail(breaker)
    await _fail(breaker)
    assert breaker.state == "closed"
    assert (await _complete(breaker)).content == "segue"
    assert len(inner.calls) == 7


async def test_meio_aberto_com_falha_reabre_e_espera_outro_open_s():
    clock = FakeMonotonic()
    inner = ScriptedLLM([*_down(3), LLMUnavailableError("ainda caído"), "voltou"])
    breaker = _breaker(inner, clock, failure_threshold=3, open_s=30)
    for _ in range(3):
        await _fail(breaker)

    clock.advance(30)
    assert "ainda caído" in await _fail(breaker)

    assert breaker.state == "open"
    assert "circuito aberto" in await _fail(breaker)
    assert len(inner.calls) == 4
    clock.advance(30)
    assert (await _complete(breaker)).content == "voltou"


async def test_meio_aberto_com_chamadas_concorrentes_so_uma_vai_ao_inner():
    clock = FakeMonotonic()
    inner = GatedLLM(fail_first=3)
    breaker = _breaker(inner, clock, failure_threshold=3, open_s=30)
    for _ in range(3):
        await _fail(breaker)
    clock.advance(30)

    async def liberar() -> None:
        await inner.entered.wait()
        inner.release.set()

    resultados = await asyncio.wait_for(
        asyncio.gather(*(_complete(breaker) for _ in range(5)), liberar(), return_exceptions=True),
        timeout=5,
    )

    respostas = resultados[:5]
    sucessos = [r for r in respostas if isinstance(r, LLMResult)]
    recusas = [r for r in respostas if isinstance(r, LLMUnavailableError)]
    assert inner.calls == 3 + 1
    assert len(sucessos) == 1
    assert len(recusas) == 4
    assert all("circuito aberto" in str(r) for r in recusas)
    assert breaker.state == "closed"


# ------------------------------------------------------------------------ erro do pedido


async def test_bad_request_nao_conta_como_falha_e_e_repassado():
    clock = FakeMonotonic()
    inner = ScriptedLLM([LLMBadRequestError("400 do provider") for _ in range(4)] + ["ok"])
    breaker = _breaker(inner, clock, failure_threshold=2)

    for _ in range(4):
        assert "400 do provider" in await _fail(breaker, LLMBadRequestError)

    assert breaker.state == "closed"
    assert (await _complete(breaker)).content == "ok"
    assert len(inner.calls) == 5


# ------------------------------------------------------------------------------ fallback


def test_llm_result_tem_provider_opcional_none_por_padrao():
    result = LLMResult(content="x", model="m", input_tokens=1, output_tokens=1)

    assert result.provider is None
    assert LLMResult(**{**result.model_dump(), "provider": "primario"}).provider == "primario"


async def test_fallback_com_primario_ok_nao_chama_o_secundario():
    primario = NamedLLM("primario", ["do primário"])
    secundario = NamedLLM("secundario", ["do secundário"])

    result = await _complete(_resilience().FallbackLLM([primario, secundario]))

    assert result.content == "do primário"
    assert result.provider == "primario"
    assert secundario.calls == []


async def test_fallback_com_primario_indisponivel_responde_pelo_secundario():
    primario = NamedLLM("primario", _down(1, "timeout do primário"))
    secundario = NamedLLM("secundario", ["do secundário"])

    result = await _complete(_resilience().FallbackLLM([primario, secundario]))

    assert result.content == "do secundário"
    assert result.model == "modelo-secundario"
    assert result.provider == "secundario"
    assert secundario.calls == [MESSAGES]


async def test_fallback_com_circuito_do_primario_aberto_vai_direto_ao_secundario():
    clock = FakeMonotonic()
    primario_inner = ScriptedLLM(_down(1))
    primario = _breaker(primario_inner, clock, name="primario", failure_threshold=1)
    secundario = NamedLLM("secundario", ["um", "dois"])
    fallback = _resilience().FallbackLLM([primario, secundario])

    assert (await _complete(fallback)).provider == "secundario"
    result = await _complete(fallback)

    assert result.content == "dois"
    assert result.provider == "secundario"
    assert len(primario_inner.calls) == 1


async def test_fallback_com_todos_indisponiveis_levanta_com_o_motivo_de_cada_um():
    primario = NamedLLM("primario", _down(1, "timeout do primário"))
    secundario = NamedLLM("secundario", _down(1, "503 do secundário"))

    message = await _fail(_resilience().FallbackLLM([primario, secundario]))

    for trecho in ("primario", "timeout do primário", "secundario", "503 do secundário"):
        assert trecho in message


async def test_fallback_nao_cai_para_o_secundario_em_bad_request():
    primario = NamedLLM("primario", [LLMBadRequestError("400 do primário")])
    secundario = NamedLLM("secundario", ["do secundário"])

    assert "400 do primário" in await _fail(
        _resilience().FallbackLLM([primario, secundario]), LLMBadRequestError
    )
    assert secundario.calls == []
