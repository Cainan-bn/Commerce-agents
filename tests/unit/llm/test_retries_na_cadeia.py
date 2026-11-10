"""Novas tentativas só no último provider da cadeia (ADR 0019, gargalo 1).

Contrato fixado:
- `LLM_MAX_RETRIES` e `LLM_TIMEOUT_S` configuram o `OpenAICompatibleProvider` (padrões 3 e 60.0);
  `LLM_MAX_RETRIES` também configura o `OpenCodeCliProvider` (padrão 2; o timeout dele continua
  em `LLM_OPENCODE_TIMEOUT_S`). Zero novas tentativas é válido; negativo ou não numérico é
  `ValueError` com o nome da variável. `LLM_FALLBACK_MAX_RETRIES` e `LLM_FALLBACK_TIMEOUT_S` valem
  para o secundário;
- `build_resilient_llm`: com secundário, o primário é montado com `LLM_MAX_RETRIES=0` (qualquer
  que seja o configurado) e o secundário mantém os dele; sem secundário, nada muda;
- comportamento: com secundário, uma chamada faz 1 requisição ao primário caído e 1 ao
  secundário, sem espera; depois de `failure_threshold` chamadas o circuito do primário abre e a
  seguinte não toca o primário.
"""

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from commerce_agents.application.dto.views import LLMMessage
from tests.fakes.clock import FakeMonotonic
from tests.fakes.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.unit

KEY = "chave-de-teste"  # pragma: allowlist secret
OPENAI = {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "modelo-a", "LLM_API_KEY": KEY}
FALLBACK = {
    "LLM_FALLBACK_PROVIDER": "openai-compatible",
    "LLM_FALLBACK_MODEL": "modelo-b",
    "LLM_FALLBACK_BASE_URL": "http://secundario.test/v1",
    "LLM_FALLBACK_API_KEY": KEY,
}
MESSAGES = [LLMMessage(role="user", content="oi")]


def _build(env: Mapping[str, str]) -> Any:
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env

    return build_provider_from_env(env)


def _resilience() -> Any:
    from commerce_agents.infrastructure.llm import resilience

    return resilience


# ------------------------------------------------------------------ 1. ambiente


def test_openai_compativel_mantem_os_padroes_sem_variaveis():
    provider = _build(OPENAI)

    assert provider._max_retries == 3
    assert provider._timeout == 60.0


def test_openai_compativel_le_novas_tentativas_e_timeout_do_ambiente():
    provider = _build({**OPENAI, "LLM_MAX_RETRIES": "0", "LLM_TIMEOUT_S": "7.5"})

    assert provider._max_retries == 0
    assert provider._timeout == 7.5


def test_opencode_le_novas_tentativas_e_mantem_o_proprio_timeout(tmp_path: Path):
    env = {"LLM_MODEL": "opencode-go/modelo", "LLM_WORKDIR": str(tmp_path)}

    assert _build(env)._max_retries == 2
    provider = _build({**env, "LLM_MAX_RETRIES": "5", "LLM_OPENCODE_TIMEOUT_S": "45"})
    assert provider._max_retries == 5
    assert provider._timeout == 45


@pytest.mark.parametrize(
    ("variavel", "valor"),
    [
        ("LLM_MAX_RETRIES", "-1"),
        ("LLM_MAX_RETRIES", "tres"),
        ("LLM_MAX_RETRIES", "1.5"),
        ("LLM_TIMEOUT_S", "0"),
        ("LLM_TIMEOUT_S", "-2"),
        ("LLM_TIMEOUT_S", "rapido"),
    ],
)
def test_valor_invalido_e_erro_com_o_nome_da_variavel(variavel: str, valor: str):
    with pytest.raises(ValueError, match=variavel):
        _build({**OPENAI, variavel: valor})


# ------------------------------------------------------------------ 2. composição


class _Builder:
    """`build_provider` falso: registra o ambiente que cada elo da cadeia recebeu."""

    def __init__(self) -> None:
        self.envs: list[dict[str, str]] = []

    def __call__(self, env: Mapping[str, str]) -> ScriptedLLM:
        self.envs.append(dict(env))
        return ScriptedLLM([])


def _compose(env: Mapping[str, str]) -> tuple[Any, _Builder]:
    builder = _Builder()
    llm = _resilience().build_resilient_llm(env, build_provider=builder, clock=FakeMonotonic())
    return llm, builder


def test_com_secundario_o_primario_vem_sem_novas_tentativas():
    _, builder = _compose({**OPENAI, **FALLBACK, "LLM_MAX_RETRIES": "4"})

    primario, secundario = builder.envs
    assert primario["LLM_MAX_RETRIES"] == "0"
    assert secundario.get("LLM_MAX_RETRIES") != "0"


def test_secundario_usa_as_variaveis_de_fallback():
    env = {
        **OPENAI,
        **FALLBACK,
        "LLM_TIMEOUT_S": "30",
        "LLM_FALLBACK_MAX_RETRIES": "1",
        "LLM_FALLBACK_TIMEOUT_S": "12",
    }

    _, builder = _compose(env)

    primario, secundario = builder.envs
    assert primario["LLM_MAX_RETRIES"] == "0"
    assert primario["LLM_TIMEOUT_S"] == "30"
    assert secundario["LLM_MAX_RETRIES"] == "1"
    assert secundario["LLM_TIMEOUT_S"] == "12"


def test_secundario_sem_variaveis_proprias_fica_com_o_padrao():
    _, builder = _compose({**OPENAI, **FALLBACK})

    assert "LLM_MAX_RETRIES" not in builder.envs[1]


def test_sem_secundario_o_unico_provider_usa_o_ambiente_como_esta():
    _, builder = _compose({**OPENAI, "LLM_MAX_RETRIES": "4"})

    assert builder.envs == [{**OPENAI, "LLM_MAX_RETRIES": "4"}]


def test_cadeia_real_monta_o_primario_com_zero_e_o_secundario_com_o_dele():
    env = {**OPENAI, **FALLBACK, "LLM_MAX_RETRIES": "4", "LLM_FALLBACK_MAX_RETRIES": "2"}

    llm = _resilience().build_resilient_llm(env, clock=FakeMonotonic())

    primario, secundario = llm.providers
    assert primario.inner._max_retries == 0
    assert secundario.inner._max_retries == 2


# ------------------------------------------------------------------ 3. comportamento


class _Transport:
    """Primário (`primario.test`) sempre 503; secundário responde 200."""

    def __init__(self) -> None:
        self.hosts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.hosts.append(request.url.host)
        if request.url.host == "primario.test":
            return httpx.Response(503, json={"error": "fora do ar"})
        return httpx.Response(
            200,
            json={
                "model": "modelo-b",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> _Transport:
    from commerce_agents.infrastructure.llm import openai_compatible

    fake = _Transport()
    real_client = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", client)
    return fake


def _chain(env_extra: Mapping[str, str] | None = None) -> Any:
    env = {
        **OPENAI,
        "LLM_BASE_URL": "http://primario.test/v1",
        **FALLBACK,
        **(env_extra or {}),
    }
    return _resilience().build_resilient_llm(env, clock=FakeMonotonic())


async def test_com_secundario_uma_chamada_vai_uma_vez_a_cada_provider_sem_espera(
    transport: _Transport,
):
    llm = _chain({"LLM_MAX_RETRIES": "3"})

    started = time.monotonic()
    result = await llm.complete(MESSAGES, max_tokens=8)

    assert result.provider == "secundario"
    assert transport.hosts == ["primario.test", "secundario.test"]
    assert time.monotonic() - started < 1.0  # sem backoff entre tentativas


async def test_circuito_do_primario_abre_e_a_chamada_seguinte_nao_o_toca(transport: _Transport):
    llm = _chain()
    threshold = llm.providers[0]._threshold

    for _ in range(threshold):
        await llm.complete(MESSAGES, max_tokens=8)
    assert transport.hosts.count("primario.test") == threshold
    assert llm.providers[0].state == "open"

    await llm.complete(MESSAGES, max_tokens=8)

    assert transport.hosts.count("primario.test") == threshold
    assert transport.hosts.count("secundario.test") == threshold + 1
