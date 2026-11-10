"""Provider gravado do modo demonstração (ADR 0020).

Contrato fixado (`commerce_agents.infrastructure.llm.recorded`):
- `llm_cassette_key(messages, max_tokens)`: a MESMA chave do eval (`evals.replay.llm_key`), que
  passa a usá-la; o valor de referência abaixo garante que o cassete do eval-ci continua válido;
- `RecordedLLMProvider(cassette_path)`: chave presente devolve o `LLMResult` gravado
  (`provider="recorded"`, `cost_usd=None`); chave ausente NÃO levanta e devolve `DEMO_MISS_REPLY`;
  cassete inexistente ou ilegível é `ValueError` na construção, citando o arquivo;
- `build_provider_from_env`: `LLM_PROVIDER=recorded` com `LLM_CASSETTE` obrigatório;
  `llm_from_env` monta o gravado mesmo sem `LLM_MODEL`;
- roteador com miss cai em `ambiguous` e o turno termina com resposta ao cliente.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.dto.views import LLMMessage
from tests.fakes.agents import StoreStub
from tests.fakes.graph import GraphHarness

pytestmark = pytest.mark.unit

MESSAGES = [
    LLMMessage(role="system", content="Você é um atendente."),
    LLMMessage(role="user", content="onde está meu pedido?"),
]
# sha256 da serialização canônica de hoje (ADR 0016): mudar a chave invalida os cassetes.
GOLDEN_KEY = (
    "2aec3a209d78771522b2b4dee84161d3"  # pragma: allowlist secret
    "92f4d4a12944a899191e25f73d08576d"  # pragma: allowlist secret
)


def _recorded() -> Any:
    from commerce_agents.infrastructure.llm import recorded

    return recorded


def _cassette(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / "demo.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    lines.append(json.dumps({"kind": "meta", "subset": "demo"}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _record(messages: list[LLMMessage], max_tokens: int, content: str) -> dict[str, Any]:
    return {
        "kind": "llm",
        "key": _recorded().llm_cassette_key(messages, max_tokens),
        "content": content,
        "input_tokens": 12,
        "output_tokens": 7,
    }


# ------------------------------------------------------------------ chave


def test_chave_e_a_mesma_do_eval():
    from evals.replay import llm_key

    for max_tokens in (60, 800):
        assert _recorded().llm_cassette_key(MESSAGES, max_tokens) == llm_key(MESSAGES, max_tokens)


def test_chave_nao_mudou_e_o_cassete_do_eval_ci_continua_valido():
    assert _recorded().llm_cassette_key(MESSAGES, 64) == GOLDEN_KEY


# ------------------------------------------------------------------ provider


async def test_chave_presente_devolve_o_resultado_gravado(tmp_path: Path):
    path = _cassette(tmp_path, [_record(MESSAGES, 64, "Seu pedido está a caminho.")])

    result = await _recorded().RecordedLLMProvider(path).complete(MESSAGES, max_tokens=64)

    assert result.content == "Seu pedido está a caminho."
    assert (result.input_tokens, result.output_tokens) == (12, 7)
    assert result.provider == "recorded"
    assert result.cost_usd is None


async def test_chave_ausente_nao_levanta_e_devolve_o_aviso_de_demonstracao(tmp_path: Path):
    recorded = _recorded()
    path = _cassette(tmp_path, [_record(MESSAGES, 64, "gravado")])

    result = await recorded.RecordedLLMProvider(path).complete(MESSAGES, max_tokens=999)

    # 10-09a: o miss é uma resposta FINAL do protocolo do especialista com o aviso.
    from commerce_agents.application.agents.protocol import FinalAnswer, parse_agent_action

    action = parse_agent_action(result.content)
    assert isinstance(action, FinalAnswer) and action.text == recorded.DEMO_MISS_REPLY
    assert result.provider == "recorded"
    assert result.cost_usd is None


def test_aviso_de_miss_fala_do_modo_demonstracao_e_das_mensagens_sugeridas():
    reply = _recorded().DEMO_MISS_REPLY.lower()

    assert "modo demonstração" in reply
    assert "sugerid" in reply


def test_cassete_inexistente_e_erro_claro(tmp_path: Path):
    missing = tmp_path / "nao-existe.jsonl"

    with pytest.raises(ValueError, match="nao-existe.jsonl"):
        _recorded().RecordedLLMProvider(missing)


def test_cassete_ilegivel_e_erro_claro(tmp_path: Path):
    path = tmp_path / "quebrado.jsonl"
    path.write_text('{"kind": "llm", "key": \n', encoding="utf-8")

    with pytest.raises(ValueError, match="quebrado.jsonl"):
        _recorded().RecordedLLMProvider(path)


# ------------------------------------------------------------------ ambiente


def test_build_provider_from_env_monta_o_gravado(tmp_path: Path):
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env

    path = _cassette(tmp_path, [])
    provider = build_provider_from_env({"LLM_PROVIDER": "recorded", "LLM_CASSETTE": str(path)})

    assert isinstance(provider, _recorded().RecordedLLMProvider)


def test_gravado_sem_llm_cassette_e_erro_com_o_nome_da_variavel():
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env

    with pytest.raises(ValueError, match="LLM_CASSETTE"):
        build_provider_from_env({"LLM_PROVIDER": "recorded"})


def test_llm_from_env_monta_o_gravado_mesmo_sem_llm_model(tmp_path: Path):
    from commerce_agents.interfaces import composition

    path = _cassette(tmp_path, [])
    llm = composition.llm_from_env({"LLM_PROVIDER": "recorded", "LLM_CASSETTE": str(path)})

    assert not isinstance(llm, composition.UnconfiguredLLM)
    assert isinstance(llm.inner, _recorded().RecordedLLMProvider)  # dentro do breaker


# ------------------------------------------------------------------ grafo


async def test_roteador_com_miss_cai_em_ambiguous_sem_excecao(tmp_path: Path):
    from commerce_agents.infrastructure.agents.router import LLMIntentRouter

    provider = _recorded().RecordedLLMProvider(_cassette(tmp_path, []))

    decision = await LLMIntentRouter(provider).route("mensagem fora do roteiro")

    assert decision.intent == "ambiguous"
    assert decision.confidence == 0.0


async def test_turno_com_miss_termina_com_resposta_ao_cliente(tmp_path: Path):
    from commerce_agents.infrastructure.agents.router import LLMIntentRouter

    provider = _recorded().RecordedLLMProvider(_cassette(tmp_path, []))
    harness = GraphHarness(provider, StoreStub({}), LLMIntentRouter(provider))

    state = await harness.turn("web:demo-1", "mensagem fora do roteiro", message_id="m-demo-1")

    assert isinstance(state["reply"], str) and state["reply"].strip()
