"""Embedder determinístico para testes: bag-of-words com hash estável (sha256), normalizado L2.

`calls_documents` conta os textos embutidos como documento (é o `embeddings_computed` medido
pelos testes de ingestão) e `calls_queries` conta as consultas embutidas.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

PENDING_FAILURE = RuntimeError("falha injetada no embedder")


class HashingEmbedder:
    def __init__(self, dimension: int = 384, model_name: str = "hashing-test") -> None:
        self._dimension = dimension
        self._model_name = model_name
        self.calls_documents = 0
        self.calls_queries = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls_documents += len(texts)
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls_queries += 1
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self._dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


class FailingEmbedder(HashingEmbedder):
    """Falha ao embutir documentos a partir da `fail_after`-ésima chamada cumulativa de texto."""

    def __init__(self, fail_after: int, **options: object) -> None:
        super().__init__(**options)  # type: ignore[arg-type]
        self._fail_after = fail_after

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.calls_documents + len(texts) > self._fail_after:
            raise PENDING_FAILURE
        return await super().embed_documents(texts)
