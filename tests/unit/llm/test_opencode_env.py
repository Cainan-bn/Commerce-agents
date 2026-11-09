"""`build_provider_from_env` lê LLM_OPENCODE_TIMEOUT_S e LLM_OPENCODE_MAX_CONCURRENCY (opcionais).

Só monta o provider a partir de um dict de ambiente: nenhum subprocesso é iniciado.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

MODEL = "opencode-go/claude-haiku-5-5"


def _build(workdir: Path, **extra: str):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env

    return build_provider_from_env({"LLM_MODEL": MODEL, "LLM_WORKDIR": str(workdir), **extra})


def test_sem_variaveis_usa_timeout_180_e_concorrencia_4(tmp_path: Path):
    provider = _build(tmp_path)

    assert provider._timeout == 180
    assert provider._semaphore._value == 4


def test_le_timeout_e_concorrencia_do_ambiente(tmp_path: Path):
    provider = _build(tmp_path, LLM_OPENCODE_TIMEOUT_S="45.5", LLM_OPENCODE_MAX_CONCURRENCY="2")

    assert provider._timeout == 45.5
    assert provider._semaphore._value == 2


@pytest.mark.parametrize(
    ("variavel", "valor"),
    [
        ("LLM_OPENCODE_TIMEOUT_S", "abc"),
        ("LLM_OPENCODE_TIMEOUT_S", "0"),
        ("LLM_OPENCODE_TIMEOUT_S", "-3"),
        ("LLM_OPENCODE_MAX_CONCURRENCY", "0"),
        ("LLM_OPENCODE_MAX_CONCURRENCY", "muitos"),
        ("LLM_OPENCODE_MAX_CONCURRENCY", "1.5"),
    ],
)
def test_valor_invalido_e_erro_claro_com_o_nome_da_variavel(
    tmp_path: Path, variavel: str, valor: str
):
    with pytest.raises(ValueError) as invalid:
        _build(tmp_path, **{variavel: valor})

    assert variavel in str(invalid.value)
