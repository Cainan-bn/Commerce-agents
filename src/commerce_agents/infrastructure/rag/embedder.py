"""Embeddings locais com fastembed (ADR 0012): paraphrase-multilingual-MiniLM-L12-v2, 384 dim."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol

DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIMENSION = 384


class _TextModel(Protocol):
    def embed(self, documents: list[str]) -> Iterable[Any]: ...


def _load_fastembed(model_name: str) -> _TextModel:  # pragma: no cover - baixa o modelo real
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name)


def _normalize(vector: Iterable[Any]) -> list[float]:
    values = [float(component) for component in vector]
    norm = math.sqrt(sum(value * value for value in values))
    return values if norm == 0 else [value / norm for value in values]


class FastEmbedEmbedder:
    """Implementa ``Embedder``; o modelo ONNX é carregado no primeiro uso, fora do loop."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        *,
        model_factory: Callable[[str], _TextModel] = _load_fastembed,
    ) -> None:
        self._model_name = model_name
        self._model_factory = model_factory
        self._model: _TextModel | None = None
        self._lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIMENSION

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._embed(list(texts))

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        model = await self._ensure_model()
        return await asyncio.to_thread(lambda: [_normalize(v) for v in model.embed(texts)])

    async def _ensure_model(self) -> _TextModel:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._model_factory, self._model_name)
            return self._model
