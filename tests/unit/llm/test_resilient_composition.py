"""Composição do provider resiliente por ambiente (ADR 0017).

Contrato fixado: `build_resilient_llm(env, *, build_provider=build_provider_from_env,
clock=time.monotonic)` em `infrastructure/llm/resilience.py`.
- Só o primário (`LLM_*`): `CircuitBreakerLLM` de nome "primario" sobre `build_provider(env)`.
- Com `LLM_FALLBACK_PROVIDER` e `LLM_FALLBACK_MODEL`: `FallbackLLM` cujo `providers` é
  [breaker "primario", breaker "secundario"]; o secundário é montado por `build_provider` com
  `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL` e `LLM_API_KEY` vindos de `LLM_FALLBACK_*`, sem
  herdar a URL nem a chave do primário.
- Fallback incompleto: `ValueError` com o nome da variável que falta.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from tests.fakes.clock import FakeMonotonic
from tests.fakes.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.unit

PRIMARY = {
    "LLM_PROVIDER": "openai-compatible",
    "LLM_MODEL": "modelo-primario",
    "LLM_BASE_URL": "https://primario.example",
    "LLM_API_KEY": "chave-primario",  # pragma: allowlist secret
}


def _resilience() -> Any:
    from commerce_agents.infrastructure.llm import resilience

    return resilience


class Builder:
    """`build_provider` falso: registra o ambiente recebido e devolve um provider roteirizado."""

    def __init__(self) -> None:
        self.envs: list[dict[str, str]] = []
        self.built: list[ScriptedLLM] = []

    def __call__(self, env: Mapping[str, str]) -> ScriptedLLM:
        self.envs.append(dict(env))
        provider = ScriptedLLM([], model=env.get("LLM_MODEL", ""))
        self.built.append(provider)
        return provider


def _build(env: Mapping[str, str], builder: Builder) -> Any:
    return _resilience().build_resilient_llm(env, build_provider=builder, clock=FakeMonotonic())


def test_so_primario_vira_circuit_breaker_sobre_o_provider_do_ambiente():
    builder = Builder()

    llm = _build(PRIMARY, builder)

    assert isinstance(llm, _resilience().CircuitBreakerLLM)
    assert llm.name == "primario"
    assert llm.inner is builder.built[0]
    assert builder.envs == [PRIMARY]


def test_com_fallback_vira_cadeia_de_dois_breakers_primario_e_secundario():
    builder = Builder()
    env = {
        **PRIMARY,
        "LLM_FALLBACK_PROVIDER": "opencode-cli",
        "LLM_FALLBACK_MODEL": "modelo-secundario",
        "LLM_FALLBACK_BASE_URL": "https://secundario.example",
        "LLM_FALLBACK_API_KEY": "chave-secundario",  # pragma: allowlist secret
    }

    llm = _build(env, builder)

    resilience = _resilience()
    assert isinstance(llm, resilience.FallbackLLM)
    primario, secundario = llm.providers
    assert all(isinstance(p, resilience.CircuitBreakerLLM) for p in llm.providers)
    assert (primario.name, secundario.name) == ("primario", "secundario")
    assert (primario.inner, secundario.inner) == tuple(builder.built)
    env_secundario = builder.envs[1]
    assert env_secundario["LLM_PROVIDER"] == "opencode-cli"
    assert env_secundario["LLM_MODEL"] == "modelo-secundario"
    assert env_secundario["LLM_BASE_URL"] == "https://secundario.example"
    assert env_secundario["LLM_API_KEY"] == "chave-secundario"  # pragma: allowlist secret


def test_secundario_sem_url_nem_chave_nao_herda_as_do_primario():
    builder = Builder()
    env = {
        **PRIMARY,
        "LLM_FALLBACK_PROVIDER": "opencode-cli",
        "LLM_FALLBACK_MODEL": "modelo-secundario",
    }

    _build(env, builder)

    env_secundario = builder.envs[1]
    assert "chave-primario" not in env_secundario.values()
    assert "https://primario.example" not in env_secundario.values()


@pytest.mark.parametrize(
    ("presente", "faltando"),
    [
        ({"LLM_FALLBACK_PROVIDER": "opencode-cli"}, "LLM_FALLBACK_MODEL"),
        ({"LLM_FALLBACK_MODEL": "modelo-secundario"}, "LLM_FALLBACK_PROVIDER"),
    ],
)
def test_fallback_incompleto_e_value_error_com_o_nome_da_variavel(
    presente: dict[str, str], faltando: str
):
    with pytest.raises(ValueError, match=faltando):
        _build({**PRIMARY, **presente}, Builder())


# ---------------------------------------------------------------------------- composition


def test_llm_from_env_sem_modelo_mantem_o_placeholder():
    from commerce_agents.interfaces import composition

    assert isinstance(composition.llm_from_env({}), composition.UnconfiguredLLM)


def test_llm_from_env_com_modelo_envolve_o_provider_real_no_breaker():
    from commerce_agents.infrastructure.llm.openai_compatible import OpenAICompatibleProvider
    from commerce_agents.interfaces import composition

    llm = composition.llm_from_env(PRIMARY)

    assert isinstance(llm, _resilience().CircuitBreakerLLM)
    assert isinstance(llm.inner, OpenAICompatibleProvider)


def test_llm_from_env_com_fallback_monta_a_cadeia():
    from commerce_agents.interfaces import composition

    llm = composition.llm_from_env(
        {
            **PRIMARY,
            "LLM_FALLBACK_PROVIDER": "openai-compatible",
            "LLM_FALLBACK_MODEL": "modelo-secundario",
            "LLM_FALLBACK_API_KEY": "chave-secundario",  # pragma: allowlist secret
        }
    )

    assert isinstance(llm, _resilience().FallbackLLM)
    assert [p.name for p in llm.providers] == ["primario", "secundario"]
