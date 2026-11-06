"""OpenCodeCliProvider (ADR 0015, adendo): transporte pelo CLI `opencode run`, sem shell.

Contrato do runner injetável: `runner(argv, *, timeout) -> (returncode, stdout, stderr)`.
"""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.dto.views import LLMMessage, LLMResult

pytestmark = pytest.mark.unit

MODEL = "opencode-go/claude-haiku-5-5"
MESSAGES = [
    LLMMessage(role="system", content="Você é um atendente."),
    LLMMessage(role="user", content="oi"),
    LLMMessage(role="assistant", content="Olá!"),
    LLMMessage(role="user", content="quero saber do pedido"),
]


def _text_event(text: str) -> str:
    return json.dumps({"type": "text", "part": {"type": "text", "text": text}})


def _finish_event(
    input_tokens: int, output_tokens: int, cost: float, cache_read: int = 0, cache_write: int = 0
) -> str:
    return json.dumps(
        {
            "type": "step_finish",
            "part": {
                "type": "step-finish",
                "cost": cost,
                "tokens": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "cache": {"read": cache_read, "write": cache_write},
                },
            },
        }
    )


def _stdout(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _provider(runner: Any, workdir: Path, sleeps: list[float] | None = None, **options: Any):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

    async def record_sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return OpenCodeCliProvider(
        options.pop("model", MODEL),
        workdir=workdir,
        runner=runner,
        sleep=record_sleep,
        **options,
    )


def _scripted_runner(outputs: Sequence[Any]):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []
    queue = list(outputs)

    async def runner(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
        calls.append(argv)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        return item

    return runner, calls


# ----------------------------------------------------------------- argv e segurança


async def test_argv_exato_com_mensagem_como_um_unico_argumento(tmp_path: Path):
    runner, calls = _scripted_runner(
        [(0, _stdout(_text_event("ok"), _finish_event(1, 1, 0.0)), "")]
    )

    await _provider(runner, tmp_path).complete(MESSAGES, max_tokens=64)

    argv = calls[0]
    assert argv[:9] == [
        "opencode",
        "run",
        "--dir",
        str(tmp_path),
        "-m",
        MODEL,
        "--agent",
        "plain",
        "--format",
    ]
    assert argv[9] == "json"
    assert len(argv) == 11
    assert argv[10].startswith("[SISTEMA]")


async def test_aspas_crases_cifrao_e_quebras_nao_mudam_o_argv(tmp_path: Path):
    hostile = [
        LLMMessage(
            role="user", content="`rm -rf /` $(whoami) \"aspas\" 'simples'\nlinha; echo x && y"
        )
    ]
    runner, calls = _scripted_runner(
        [(0, _stdout(_text_event("ok"), _finish_event(1, 1, 0.0)), "")]
    )

    await _provider(runner, tmp_path).complete(hostile, max_tokens=64)

    argv = calls[0]
    assert len(argv) == 11
    assert "`rm -rf /` $(whoami)" in argv[10]
    assert argv[9] == "json"


async def test_default_nao_usa_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (_stdout(_text_event("oi"), _finish_event(1, 1, 0.0)).encode(), b"")

    async def fake_exec(*args: Any, **kwargs: Any) -> FakeProcess:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return FakeProcess()

    def forbidden_shell(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("create_subprocess_shell não pode ser usado")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_shell)

    from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

    provider = OpenCodeCliProvider(MODEL, workdir=tmp_path)
    await provider.complete(MESSAGES, max_tokens=64)

    assert seen["args"][0] == "opencode"
    assert "shell" not in seen["kwargs"]


# ----------------------------------------------------------------- serialização


GOLDEN = (
    "[SISTEMA]\n"
    "Você é um atendente.\n"
    "\n"
    "[USUARIO]\n"
    "oi\n"
    "\n"
    "[ASSISTENTE]\n"
    "Olá!\n"
    "\n"
    "[USUARIO]\n"
    "quero saber do pedido"
)


async def test_serializacao_das_mensagens_e_golden(tmp_path: Path):
    runner, calls = _scripted_runner(
        [(0, _stdout(_text_event("ok"), _finish_event(1, 1, 0.0)), "")]
    )

    await _provider(runner, tmp_path).complete(MESSAGES, max_tokens=64)

    assert calls[0][10] == GOLDEN


# ----------------------------------------------------------------- parsing do stdout


async def test_concatena_eventos_text_e_ignora_step_start_e_linhas_de_log(tmp_path: Path):
    stdout = _stdout(
        json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
        "INFO log do opencode: iniciando",
        _text_event("Olá, "),
        _text_event("tudo bem?"),
        _finish_event(10, 5, 0.001),
    )
    runner, _ = _scripted_runner([(0, stdout, "")])

    result = await _provider(runner, tmp_path).complete(MESSAGES, max_tokens=64)

    assert isinstance(result, LLMResult)
    assert result.content == "Olá, tudo bem?"


async def test_tokens_somam_cache_na_entrada_e_saida_vem_de_output(tmp_path: Path):
    stdout = _stdout(_text_event("ok"), _finish_event(100, 40, 0.0, cache_read=30, cache_write=20))
    runner, _ = _scripted_runner([(0, stdout, "")])

    result = await _provider(runner, tmp_path).complete(MESSAGES, max_tokens=64)

    assert result.input_tokens == 150
    assert result.output_tokens == 40


async def test_model_do_resultado_e_o_configurado(tmp_path: Path):
    runner, _ = _scripted_runner([(0, _stdout(_text_event("ok"), _finish_event(1, 1, 0.0)), "")])

    result = await _provider(runner, tmp_path).complete(MESSAGES, max_tokens=64)

    assert result.model == MODEL


async def test_custo_acumula_em_last_e_total(tmp_path: Path):
    runner, _ = _scripted_runner(
        [
            (0, _stdout(_text_event("a"), _finish_event(1, 1, 0.001)), ""),
            (0, _stdout(_text_event("b"), _finish_event(1, 1, 0.002)), ""),
        ]
    )
    provider = _provider(runner, tmp_path)

    await provider.complete(MESSAGES, max_tokens=64)
    assert provider.last_cost_usd == pytest.approx(0.001)
    await provider.complete(MESSAGES, max_tokens=64)

    assert provider.last_cost_usd == pytest.approx(0.002)
    assert provider.total_cost_usd == pytest.approx(0.003)


async def test_sem_custo_no_evento_last_e_none(tmp_path: Path):
    runner, _ = _scripted_runner([(0, _stdout(_text_event("a")), "")])
    provider = _provider(runner, tmp_path)

    await provider.complete(MESSAGES, max_tokens=64)

    assert provider.last_cost_usd is None


# ----------------------------------------------------------------- falhas


async def test_retry_em_timeout_depois_sucede(tmp_path: Path):
    sleeps: list[float] = []
    runner, calls = _scripted_runner(
        [TimeoutError("demorou"), (0, _stdout(_text_event("ok"), _finish_event(1, 1, 0.0)), "")]
    )

    result = await _provider(runner, tmp_path, sleeps, max_retries=1).complete(
        MESSAGES, max_tokens=64
    )

    assert result.content == "ok"
    assert len(calls) == 2
    assert len(sleeps) == 1 and sleeps[0] > 0


@pytest.mark.parametrize(
    "output",
    [
        (0, _stdout(json.dumps({"type": "error", "error": {"name": "APIError"}})), ""),
        (1, _stdout(_text_event("parcial")), ""),
        (0, _stdout(_finish_event(1, 1, 0.0)), ""),
        TimeoutError("estourou"),
    ],
    ids=["evento-error", "returncode-nao-zero", "sem-evento-text", "timeout"],
)
async def test_falhas_do_cli_viram_indisponivel_apos_retries(tmp_path: Path, output: Any):
    from commerce_agents.infrastructure.llm.opencode_cli import LLMUnavailableError

    sleeps: list[float] = []
    runner, calls = _scripted_runner([output])

    with pytest.raises(LLMUnavailableError):
        await _provider(runner, tmp_path, sleeps, max_retries=2).complete(MESSAGES, max_tokens=64)

    assert len(calls) == 3
    assert len(sleeps) == 2


async def test_stderr_bruto_nunca_entra_no_erro(tmp_path: Path):
    from commerce_agents.infrastructure.llm.opencode_cli import LLMUnavailableError

    secret_stderr = "Authorization: Bearer sk-vazado-no-stderr-123"  # pragma: allowlist secret
    runner, _ = _scripted_runner([(1, "", secret_stderr)])

    with pytest.raises(LLMUnavailableError) as raised:
        await _provider(runner, tmp_path, max_retries=0).complete(MESSAGES, max_tokens=64)

    assert "sk-vazado" not in str(raised.value)
    assert "sk-vazado" not in repr(raised.value)


async def test_semaforo_limita_chamadas_simultaneas(tmp_path: Path):
    active = 0
    peak = 0

    async def runner(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return (0, _stdout(_text_event("ok"), _finish_event(1, 1, 0.0)), "")

    provider = _provider(runner, tmp_path, max_concurrency=2)

    await asyncio.gather(*(provider.complete(MESSAGES, max_tokens=64) for _ in range(5)))

    assert peak == 2


def test_workdir_inexistente_e_value_error(tmp_path: Path):
    from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

    with pytest.raises(ValueError):
        OpenCodeCliProvider(MODEL, workdir=tmp_path / "nao-existe")


def test_model_sem_barra_e_value_error(tmp_path: Path):
    from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

    with pytest.raises(ValueError):
        OpenCodeCliProvider("claude-haiku-5-5", workdir=tmp_path)


def test_build_provider_do_ambiente_usa_opencode_quando_nao_ha_chave(tmp_path: Path):
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env
    from commerce_agents.infrastructure.llm.opencode_cli import OpenCodeCliProvider

    provider = build_provider_from_env({"LLM_MODEL": MODEL, "LLM_WORKDIR": str(tmp_path)})

    assert isinstance(provider, OpenCodeCliProvider)
