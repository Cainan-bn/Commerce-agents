"""Port de embeddings (ADR 0012)."""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Gera vetores normalizados. O adaptador aplica prefixos específicos do modelo."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
