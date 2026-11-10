"""Provider gravado do modo demonstração (ADR 0020).

Lê um cassete no formato do eval (ADR 0016) e responde só o que foi gravado com o modelo real.
Diferente do replay do eval, chave ausente não é erro: devolve `DEMO_MISS_REPLY`.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from commerce_agents.application.dto.views import LLMMessage, LLMResult

__all__ = ["DEMO_MISS_REPLY", "RECORDED_MODEL", "RecordedLLMProvider", "llm_cassette_key"]

RECORDED_MODEL = "recorded"
DEMO_MISS_REPLY = (
    "Estou em modo demonstração e só sei responder às conversas gravadas. "
    "Experimente uma das mensagens sugeridas ao lado."
)


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
        record = self._records.get(llm_cassette_key(messages, max_tokens))
        if record is None:
            return LLMResult(
                content=DEMO_MISS_REPLY,
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
