"""Replay gravado (ADR 0016): providers e retriever de gravação e reprodução, sem LLM nem Postgres.

Cassete: JSONL com uma linha por chamada. LLM: {kind: "llm", key, content, input_tokens,
output_tokens}, chave `llm_key(messages, max_tokens)`. Retriever: {kind: "retrieval", key,
chunks}, chave `retrieval_key(query, top_k)`. Chave ausente => `CassetteMissError`.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from commerce_agents.application.dto.views import LLMMessage, LLMResult, PolicyChunk
from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.scripted_llm import ScriptedLLM

pytestmark = pytest.mark.unit

MENSAGENS = [
    LLMMessage(role="system", content="você é o agente"),
    LLMMessage(role="user", content="qual o prazo?"),
]


def _write(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), "utf-8")
    return path


def _chunk(chunk_id: str = "trocas-01") -> PolicyChunk:
    return PolicyChunk(
        chunk_id=chunk_id,
        document="trocas.md",
        section="Prazo",
        text="Trocas em até 7 dias.",
        score=0.9,
        corpus_version="v1",
    )


# ------------------------------------------------------------------------------- chaves


def test_llm_key_e_sha256_e_depende_das_mensagens_e_do_max_tokens():
    from evals.replay import llm_key

    key = llm_key(MENSAGENS, 100)

    assert len(key) == 64 and all(c in "0123456789abcdef" for c in key)
    assert key == llm_key(list(MENSAGENS), 100)
    assert key != llm_key(MENSAGENS, 101)
    assert key != llm_key([*MENSAGENS, LLMMessage(role="user", content="e?")], 100)


def test_retrieval_key_e_sha256_e_depende_da_consulta_e_do_top_k():
    from evals.replay import retrieval_key

    key = retrieval_key("prazo de troca", 4)

    assert len(key) == 64
    assert key == retrieval_key("prazo de troca", 4)
    assert key != retrieval_key("prazo de troca", 2)
    assert key != retrieval_key("prazo de devolução", 4)


# --------------------------------------------------------------------------- ReplayProvider


async def test_replay_devolve_a_resposta_gravada_para_a_chave(tmp_path: Path):
    from evals.replay import ReplayProvider, llm_key

    cassete = _write(
        tmp_path / "c.jsonl",
        [
            {
                "kind": "llm",
                "key": llm_key(MENSAGENS, 100),
                "content": '{"type": "final", "text": "7 dias"}',
                "input_tokens": 12,
                "output_tokens": 5,
            }
        ],
    )

    result = await ReplayProvider(cassete).complete(MENSAGENS, max_tokens=100)

    assert isinstance(result, LLMResult)
    assert result.content == '{"type": "final", "text": "7 dias"}'
    assert (result.input_tokens, result.output_tokens) == (12, 5)


async def test_chave_ausente_e_cassette_miss_com_instrucao_e_nao_e_erro_de_infra(tmp_path: Path):
    from evals.replay import CassetteMissError, ReplayProvider

    cassete = _write(tmp_path / "c.jsonl", [])

    with pytest.raises(CassetteMissError) as miss:
        await ReplayProvider(cassete).complete(MENSAGENS, max_tokens=100)

    assert "make eval-record" in str(miss.value)
    assert not isinstance(miss.value, LLMUnavailableError)


# ------------------------------------------------------------------------ RecordingProvider


async def test_recording_repassa_ao_provider_interno_e_grava_a_linha_llm():
    from evals.replay import RecordingProvider, llm_key

    gravados: list[dict[str, Any]] = []
    inner = ScriptedLLM(["resposta real"])

    result = await RecordingProvider(inner, gravados.append).complete(MENSAGENS, max_tokens=100)

    assert result.content == "resposta real"
    assert len(inner.calls) == 1
    assert gravados == [
        {
            "kind": "llm",
            "key": llm_key(MENSAGENS, 100),
            "content": "resposta real",
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    ]


async def test_gravar_e_reproduzir_as_mesmas_mensagens_devolve_o_mesmo_conteudo(tmp_path: Path):
    from evals.replay import RecordingProvider, ReplayProvider

    gravados: list[dict[str, Any]] = []
    gravado = await RecordingProvider(ScriptedLLM(["ida"]), gravados.append).complete(
        MENSAGENS, max_tokens=64
    )
    cassete = _write(tmp_path / "c.jsonl", gravados)

    reproduzido = await ReplayProvider(cassete).complete(MENSAGENS, max_tokens=64)

    assert reproduzido.content == gravado.content == "ida"


# --------------------------------------------------------------------------- retriever


class _InnerRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyChunk]:
        self.calls.append((query, k))
        return [_chunk("trocas-01"), _chunk("trocas-02")]


async def test_recording_retriever_grava_os_trechos_pela_chave_da_consulta():
    from evals.replay import RecordingRetriever, retrieval_key

    gravados: list[dict[str, Any]] = []
    inner = _InnerRetriever()

    chunks = await RecordingRetriever(inner, gravados.append).retrieve("prazo de troca", k=2)

    assert [c.chunk_id for c in chunks] == ["trocas-01", "trocas-02"]
    assert inner.calls == [("prazo de troca", 2)]
    assert gravados[0]["kind"] == "retrieval"
    assert gravados[0]["key"] == retrieval_key("prazo de troca", 2)
    assert [c["chunk_id"] for c in gravados[0]["chunks"]] == ["trocas-01", "trocas-02"]


async def test_replay_retriever_reproduz_os_trechos_gravados(tmp_path: Path):
    from evals.replay import RecordingRetriever, ReplayRetriever

    gravados: list[dict[str, Any]] = []
    await RecordingRetriever(_InnerRetriever(), gravados.append).retrieve("prazo de troca", k=2)
    cassete = _write(tmp_path / "c.jsonl", gravados)

    chunks = await ReplayRetriever(cassete).retrieve("prazo de troca", k=2)

    assert chunks == [_chunk("trocas-01"), _chunk("trocas-02")]


async def test_replay_retriever_sem_a_consulta_e_cassette_miss(tmp_path: Path):
    from evals.replay import CassetteMissError, ReplayRetriever

    cassete = _write(tmp_path / "c.jsonl", [])

    with pytest.raises(CassetteMissError) as miss:
        await ReplayRetriever(cassete).retrieve("prazo de troca", k=2)

    assert "make eval-record" in str(miss.value)


# ------------------------------------------------------------- miss não vira infra_error


async def test_run_scenario_propaga_cassette_miss_em_vez_de_registrar_infra_error(
    tmp_path: Path,
):
    from evals.harness import run_scenario
    from evals.replay import CassetteMissError, ReplayProvider

    from tests.fakes.evals import make_eval_deps
    from tests.fakes.traces import scenario

    deps = make_eval_deps([], intent="policy_question")
    deps.llm = ReplayProvider(_write(tmp_path / "c.jsonl", []))

    with pytest.raises(CassetteMissError):
        await run_scenario(scenario(scenario_id="POL-001", category="politicas"), deps)
