"""Guardas contra prompt injection (ADR 0010/0013): delimitadores, detecção e saída limpa."""

import re
import unicodedata

_DELIMITER = re.compile(r"<(/?)dados", re.IGNORECASE)

_INJECTION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(ignor\w*|esquec\w*|desconsider\w*)\b.{0,40}\b(instrucoes|regras|anteriores|tudo|prompt)\b",
        r"\bignore\b.{0,20}\b(previous|prior|above|all)\b",
        r"\bvoce agora e\b",
        r"\b(system|sistema)\s*(prompt\b|:)",
        r"\b(mostre|revele|exiba|repita|diga)\b.{0,30}\b(prompt|regras internas|instrucoes)\b",
        r"\b(modo desenvolvedor|developer mode|jailbreak)\b",
    )
)

_DATA_BLOCK = re.compile(r"<dados[^>]*>.*?</dados>", re.IGNORECASE | re.DOTALL)
_STRAY_TAG = re.compile(r"</?dados[^>]*>", re.IGNORECASE)
_CHAT_MARKERS = re.compile(r"<\|[^|>]*\|>|\[/?INST\]|<<\s*/?SYS\s*>>", re.IGNORECASE)
_PROMPT_LEAK = re.compile(
    r"(system prompt|prompt do sistema|instruções do sistema)\s*:?", re.IGNORECASE
)
_ACTION_JSON = re.compile(
    r'\{[^{}]*"type"\s*:\s*"(?:tool_call|final)"(?:[^{}]|\{[^{}]*\})*\}', re.DOTALL
)
_SPACES = re.compile(r"[ \t]{2,}")


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def wrap_untrusted(label: str, text: str) -> str:
    """Envolve conteúdo não confiável num único bloco `<dados ...>`; o texto não o fecha."""
    escaped = _DELIMITER.sub(lambda m: f"‹{m.group(1)}dados", text)
    return f"<dados {label}>{escaped}</dados>"


def detect_injection(text: str) -> bool:
    """Heurística de sinalização (métrica/log). A defesa real é estrutural, não esta."""
    normalized = _normalize(text)
    return any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS)


def sanitize_reply(text: str) -> str:
    """Remove da resposta ao cliente marcadores de prompt, blocos de dados e JSON de ação."""
    cleaned = _DATA_BLOCK.sub("", text)
    cleaned = _STRAY_TAG.sub("", cleaned)
    cleaned = _CHAT_MARKERS.sub("", cleaned)
    cleaned = _PROMPT_LEAK.sub("", cleaned)
    cleaned = _ACTION_JSON.sub("", cleaned)
    return _SPACES.sub(" ", cleaned).strip()
