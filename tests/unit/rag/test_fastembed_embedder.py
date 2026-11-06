"""FastEmbedEmbedder com modelo falso: normalização e carregamento preguiçoso."""

import math
from collections.abc import Iterable
from typing import Any

import pytest

from commerce_agents.infrastructure.rag.embedder import (
    DEFAULT_MODEL_NAME,
    EMBEDDING_DIMENSION,
    FastEmbedEmbedder,
)

pytestmark = pytest.mark.unit


class _FakeModel:
    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    def embed(self, documents: list[str]) -> Iterable[Any]:
        self.seen.append(list(documents))
        return ([3.0, 4.0] + [0.0] * (EMBEDDING_DIMENSION - 2) for _ in documents)


def _embedder() -> tuple[FastEmbedEmbedder, _FakeModel, list[str]]:
    model = _FakeModel()
    loads: list[str] = []

    def factory(name: str) -> _FakeModel:
        loads.append(name)
        return model

    return FastEmbedEmbedder(model_factory=factory), model, loads


def test_metadados_do_modelo():
    embedder, _, loads = _embedder()

    assert embedder.model_name == DEFAULT_MODEL_NAME
    assert embedder.dimension == EMBEDDING_DIMENSION
    assert loads == []  # carregamento preguiçoso


async def test_documentos_sem_prefixo_e_vetor_normalizado():
    embedder, model, _ = _embedder()

    vectors = await embedder.embed_documents(["a", "b"])

    assert model.seen == [["a", "b"]]
    assert len(vectors) == 2
    assert vectors[0][:2] == pytest.approx([0.6, 0.8])
    assert math.isclose(sum(v * v for v in vectors[0]), 1.0)


async def test_consulta_sem_prefixo():
    embedder, model, _ = _embedder()

    vector = await embedder.embed_query("prazo")

    assert model.seen == [["prazo"]]
    assert len(vector) == EMBEDDING_DIMENSION


async def test_lista_vazia_nao_carrega_o_modelo():
    embedder, _, loads = _embedder()

    assert await embedder.embed_documents([]) == []
    assert loads == []


async def test_modelo_e_carregado_uma_unica_vez():
    embedder, _, loads = _embedder()

    await embedder.embed_query("a")
    await embedder.embed_documents(["b"])

    assert loads == [DEFAULT_MODEL_NAME]


async def test_vetor_nulo_nao_divide_por_zero():
    class _Zero:
        def embed(self, documents: list[str]) -> Iterable[Any]:
            return ([0.0, 0.0] for _ in documents)

    embedder = FastEmbedEmbedder(model_factory=lambda name: _Zero())

    assert await embedder.embed_query("x") == [0.0, 0.0]
