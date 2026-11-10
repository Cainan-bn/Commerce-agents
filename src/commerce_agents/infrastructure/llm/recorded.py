"""Provider gravado do modo demonstração (ADR 0020).

Lê um cassete no formato do eval (ADR 0016) e responde só o que foi gravado com o modelo real.
Diferente do replay do eval, chave ausente não é erro: devolve `DEMO_MISS_REPLY` como resposta
final do protocolo do especialista (ADR 0013), para o cliente ver o aviso sem o grafo saber de
demonstração; para o roteador ela continua inválida e vira pedido de esclarecimento.
`RecordingLLM` grava esse cassete pelo caminho real (`LLM_RECORD_TO`, só `make demo-record`).
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from commerce_agents.application.dto.agents import FinalAnswer
from commerce_agents.application.dto.views import LLMMessage, LLMResult
from commerce_agents.application.ports.llm import LLMProvider
from commerce_agents.infrastructure.telemetry import RECORDED_MISS

__all__ = [
    "DEMO_MISS_REPLY",
    "RECORDED_MODEL",
    "RecordedLLMProvider",
    "RecordingLLM",
    "llm_cassette_key",
]

logger = logging.getLogger(__name__)

RECORDED_MODEL = "recorded"
DEMO_MISS_REPLY = (
    "Estou em modo demonstração e só sei responder às conversas gravadas. "
    "Experimente uma das mensagens sugeridas ao lado."
)
_MISS_CONTENT = FinalAnswer(text=DEMO_MISS_REPLY).model_dump_json()


def llm_cassette_key(messages: list[LLMMessage], max_tokens: int) -> str:
    """sha256 da serialização canônica das mensagens; mudar a chave invalida os cassetes."""
    payload = {
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "max_tokens": max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return {str(r["key"]): r for r in records if r.get("kind") == "llm"}
    except (OSError, ValueError, KeyError, AttributeError) as error:
        raise ValueError(f"cassete da demonstração ilegível: {path}") from error


class RecordedLLMProvider:
    """`LLMProvider` que reproduz o gravado; fora do roteiro, o aviso de demonstração."""

    model = RECORDED_MODEL

    def __init__(self, cassette_path: Path | str) -> None:
        self._records = _load(Path(cassette_path))

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        key = llm_cassette_key(messages, max_tokens)
        record = self._records.get(key)
        if record is None:
            RECORDED_MISS.add(1)
            logger.warning("demonstração: chamada fora do cassete (chave %s)", key[:12])
            return LLMResult(
                content=_MISS_CONTENT,
                model=RECORDED_MODEL,
                input_tokens=0,
                output_tokens=0,
                provider=RECORDED_MODEL,
            )
        return LLMResult(
            content=str(record["content"]),
            model=RECORDED_MODEL,
            input_tokens=int(record.get("input_tokens", 0)),
            output_tokens=int(record.get("output_tokens", 0)),
            provider=RECORDED_MODEL,
        )


class RecordingLLM:
    """Repassa ao `inner` e acrescenta ao cassete cada resposta real, uma linha por chave.

    Continua um cassete existente sem duplicar chaves; erro do `inner` propaga sem gravar.
    """

    def __init__(self, inner: LLMProvider, path: Path | str) -> None:
        self.inner = inner
        self._path = Path(path)
        self._keys = set(_load(self._path)) if self._path.exists() else set()

    @property
    def model(self) -> str:
        return str(getattr(self.inner, "model", ""))

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        result = await self.inner.complete(messages, max_tokens=max_tokens)
        key = llm_cassette_key(messages, max_tokens)
        if key not in self._keys:
            self._append(
                {
                    "kind": "llm",
                    "key": key,
                    "content": result.content,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
            self._keys.add(key)
        return result

    def _append(self, record: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
