"""Replay gravado do eval (ADR 0016): grava respostas do LLM e do retriever e as reproduz.

Cassete JSONL, uma linha por chamada: {kind: "llm", key, content, input_tokens, output_tokens},
{kind: "retrieval", key, chunks} e, por último, {kind: "meta", subset, scenario_pass, commit}.
As chaves são sha256 de uma serialização canônica: o cassete nunca guarda as mensagens (que
podem trazer chaves de idempotência), só as respostas.
"""

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from commerce_agents.application.dto.views import LLMMessage, LLMResult, PolicyChunk
from commerce_agents.application.ports.llm import LLMProvider
from commerce_agents.application.ports.repositories import PolicyRetriever
from commerce_agents.infrastructure.llm.recorded import llm_cassette_key

Record = dict[str, Any]
Sink = Callable[[Record], None]

REPLAY_MODEL = "replay"
_MISS_HINT = "cassete desatualizado: rode make eval-record"

# Misses do cenário corrente: o grafo e o executor engolem exceções, então o harness relança.
_misses: ContextVar[list["CassetteMissError"] | None] = ContextVar("cassette_misses", default=None)


class CassetteMissError(Exception):
    """Chamada sem resposta gravada; não é erro de infraestrutura e não é reexecutada."""


@contextmanager
def capture_misses() -> Iterator[list[CassetteMissError]]:
    """Coleta os `CassetteMissError` levantados no contexto (inclusive os engolidos depois)."""
    misses: list[CassetteMissError] = []
    token = _misses.set(misses)
    try:
        yield misses
    finally:
        _misses.reset(token)


def _miss(kind: str, key: str) -> CassetteMissError:
    error = CassetteMissError(f"{_MISS_HINT} ({kind} {key[:12]} sem gravação)")
    collected = _misses.get()
    if collected is not None:
        collected.append(error)
    return error


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def llm_key(messages: list[LLMMessage], max_tokens: int) -> str:
    """Mesma chave do provider gravado da demonstração (ADR 0020)."""
    return llm_cassette_key(messages, max_tokens)


def retrieval_key(query: str, top_k: int) -> str:
    return _digest({"query": query, "top_k": top_k})


def read_cassette(path: Path) -> list[Record]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def cassette_meta(records: Iterable[Record]) -> Record | None:
    metas = [r for r in records if r.get("kind") == "meta"]
    return metas[-1] if metas else None


def write_cassette(path: Path, records: Iterable[Record], meta: Record) -> None:
    """Escrita atômica e determinística: uma linha por chave (a última vence), meta no fim."""
    by_key = {r["key"]: r for r in records}
    lines = [by_key[key] for key in sorted(by_key)] + [meta]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in lines)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _index(path: Path, kind: str) -> dict[str, Record]:
    return {r["key"]: r for r in read_cassette(path) if r.get("kind") == kind}


class ReplayProvider:
    """`LLMProvider` que só responde o que está no cassete."""

    model = REPLAY_MODEL

    def __init__(self, cassette: Path) -> None:
        self._records = _index(cassette, "llm")

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        key = llm_key(messages, max_tokens)
        record = self._records.get(key)
        if record is None:
            raise _miss("llm", key)
        return LLMResult(
            content=record["content"],
            model=REPLAY_MODEL,
            input_tokens=record["input_tokens"],
            output_tokens=record["output_tokens"],
        )


class RecordingProvider:
    """Repassa ao provider real e grava cada resposta pela chave das mensagens."""

    def __init__(self, inner: LLMProvider, sink: Sink) -> None:
        self._inner = inner
        self._sink = sink

    @property
    def model(self) -> str:
        return str(getattr(self._inner, "model", ""))

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        result = await self._inner.complete(messages, max_tokens=max_tokens)
        self._sink(
            {
                "kind": "llm",
                "key": llm_key(messages, max_tokens),
                "content": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        )
        return result


class ReplayRetriever:
    """`PolicyRetriever` que reproduz os trechos gravados (sem Postgres nem embeddings)."""

    def __init__(self, cassette: Path) -> None:
        self._records = _index(cassette, "retrieval")

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyChunk]:
        key = retrieval_key(query, k)
        record = self._records.get(key)
        if record is None:
            raise _miss("retrieval", key)
        return [PolicyChunk.model_validate(chunk) for chunk in record["chunks"]]


class RecordingRetriever:
    """Repassa ao retriever real e grava os trechos pela chave da consulta."""

    def __init__(self, inner: PolicyRetriever, sink: Sink) -> None:
        self._inner = inner
        self._sink = sink

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyChunk]:
        chunks = await self._inner.retrieve(query, k)
        self._sink(
            {
                "kind": "retrieval",
                "key": retrieval_key(query, k),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            }
        )
        return chunks
