"""Gravação da demonstração pelo caminho real (ADR 0020, TASK-10-03a).

Contrato fixado (`commerce_agents.infrastructure.llm.recorded`):
- `RecordingLLM(inner, path)`: repassa ao `inner` (exposto como `.inner`) e acrescenta uma linha
  por chamada no formato que `RecordedLLMProvider` lê; chave repetida não duplica linha; erro do
  `inner` propaga e nada é gravado;
- `build_resilient_llm` com `LLM_RECORD_TO=<path>`: o gravador fica DENTRO do breaker
  (breaker -> gravador -> adaptador), para só respostas reais irem ao cassete; com
  `LLM_PROVIDER=recorded`, `LLM_RECORD_TO` é `ValueError`;
- miss observável: `RecordedLLMProvider` conta `llm.recorded.miss` e loga WARNING com a chave,
  sem texto do cliente.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.dto.views import LLMMessage
from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.clock import FakeMonotonic
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.telemetry import collected

pytestmark = pytest.mark.unit

SENTINELA = "texto-sentinela-do-cliente-1003a"


def _messages(text: str) -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Você é o agente de pedidos."),
        LLMMessage(role="user", content=text),
    ]


def _recorded() -> Any:
    from commerce_agents.infrastructure.llm import recorded

    return recorded


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ------------------------------------------------------------------ RecordingLLM


async def test_grava_e_o_provider_gravado_reproduz_pelas_mesmas_chaves(tmp_path: Path):
    recorded = _recorded()
    path = tmp_path / "cassette.jsonl"
    textos = ["onde está o pedido O000001?", "e o O000002?", "obrigado"]
    respostas = ['{"type":"final","text":"a"}', '{"type":"final","text":"b"}', "c"]
    recorder = recorded.RecordingLLM(ScriptedLLM(respostas), path)

    gravadas = [await recorder.complete(_messages(t), max_tokens=64) for t in textos]

    assert [r.content for r in gravadas] == respostas
    assert len(_lines(path)) == 3
    replay = recorded.RecordedLLMProvider(path)
    for texto, resposta in zip(textos, respostas, strict=True):
        result = await replay.complete(_messages(texto), max_tokens=64)
        assert result.content == resposta


async def test_linha_no_formato_do_cassete(tmp_path: Path):
    recorded = _recorded()
    path = tmp_path / "cassette.jsonl"
    messages = _messages("oi")

    await recorded.RecordingLLM(ScriptedLLM(["olá"]), path).complete(messages, max_tokens=32)

    (line,) = _lines(path)
    assert line["kind"] == "llm"
    assert line["key"] == recorded.llm_cassette_key(messages, 32)
    assert line["content"] == "olá"
    assert {"input_tokens", "output_tokens"} <= set(line)


async def test_chave_repetida_nao_duplica_linha(tmp_path: Path):
    path = tmp_path / "cassette.jsonl"
    recorder = _recorded().RecordingLLM(ScriptedLLM(["um", "dois"]), path)

    await recorder.complete(_messages("mesma pergunta"), max_tokens=64)
    await recorder.complete(_messages("mesma pergunta"), max_tokens=64)

    assert len(_lines(path)) == 1


async def test_continua_um_cassete_existente_sem_duplicar(tmp_path: Path):
    recorded = _recorded()
    path = tmp_path / "cassette.jsonl"
    await recorded.RecordingLLM(ScriptedLLM(["um"]), path).complete(
        _messages("primeira"), max_tokens=64
    )

    segundo = recorded.RecordingLLM(ScriptedLLM(["um-de-novo", "dois"]), path)
    await segundo.complete(_messages("primeira"), max_tokens=64)
    await segundo.complete(_messages("segunda"), max_tokens=64)

    assert len(_lines(path)) == 2


async def test_erro_do_inner_propaga_e_nada_e_gravado(tmp_path: Path):
    path = tmp_path / "cassette.jsonl"
    recorder = _recorded().RecordingLLM(ScriptedLLM([LLMUnavailableError("fora do ar")]), path)

    with pytest.raises(LLMUnavailableError):
        await recorder.complete(_messages("oi"), max_tokens=64)

    assert _lines(path) == []


def test_expoe_o_inner(tmp_path: Path):
    inner = ScriptedLLM([])

    assert _recorded().RecordingLLM(inner, tmp_path / "c.jsonl").inner is inner


# ------------------------------------------------------------------ composição


def _resilience() -> Any:
    from commerce_agents.infrastructure.llm import resilience

    return resilience


async def test_llm_record_to_poe_o_gravador_entre_o_breaker_e_o_adaptador(tmp_path: Path):
    path = tmp_path / "cassette.jsonl"
    adaptador = ScriptedLLM(["resposta real"])
    env = {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "m", "LLM_RECORD_TO": str(path)}

    llm = _resilience().build_resilient_llm(
        env, build_provider=lambda _: adaptador, clock=FakeMonotonic()
    )

    assert isinstance(llm, _resilience().CircuitBreakerLLM)
    assert isinstance(llm.inner, _recorded().RecordingLLM)
    assert llm.inner.inner is adaptador
    await llm.complete(_messages("oi"), max_tokens=16)
    assert [line["content"] for line in _lines(path)] == ["resposta real"]


def test_sem_llm_record_to_nao_ha_gravador():
    adaptador = ScriptedLLM([])
    env = {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "m"}

    llm = _resilience().build_resilient_llm(
        env, build_provider=lambda _: adaptador, clock=FakeMonotonic()
    )

    assert llm.inner is adaptador


def test_gravar_com_o_provider_gravado_e_erro(tmp_path: Path):
    env = {
        "LLM_PROVIDER": "recorded",
        "LLM_CASSETTE": str(tmp_path / "c.jsonl"),
        "LLM_RECORD_TO": str(tmp_path / "novo.jsonl"),
    }
    (tmp_path / "c.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="LLM_RECORD_TO"):
        _resilience().build_resilient_llm(env, clock=FakeMonotonic())


# ------------------------------------------------------------------ miss observável


async def test_miss_conta_metrica_e_loga_a_chave_sem_texto_do_cliente(
    tmp_path: Path, metric_reader: Any, caplog: pytest.LogCaptureFixture
):
    recorded = _recorded()
    path = tmp_path / "cassette.jsonl"
    path.write_text("", encoding="utf-8")
    messages = _messages(SENTINELA)

    with caplog.at_level(logging.WARNING):
        result = await recorded.RecordedLLMProvider(path).complete(messages, max_tokens=64)

    assert result.content == recorded.DEMO_MISS_REPLY
    pontos = collected(metric_reader)["llm.recorded.miss"]
    assert sum(p.value for p in pontos) == 1
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert avisos
    texto = " ".join(r.getMessage() for r in avisos)
    assert recorded.llm_cassette_key(messages, 64)[:12] in texto
    assert SENTINELA not in texto


async def test_acerto_nao_conta_miss(tmp_path: Path, metric_reader: Any):
    recorded = _recorded()
    path = tmp_path / "cassette.jsonl"
    await recorded.RecordingLLM(ScriptedLLM(["gravado"]), path).complete(
        _messages("oi"), max_tokens=64
    )

    await recorded.RecordedLLMProvider(path).complete(_messages("oi"), max_tokens=64)

    assert sum(p.value for p in collected(metric_reader).get("llm.recorded.miss", [])) == 0
