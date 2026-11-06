"""rrf_fuse: Reciprocal Rank Fusion com k=60 (ADR 0005)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.unit

IDS = st.text(alphabet="abcdefgh", min_size=1, max_size=4)


def _fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    from commerce_agents.application.rag.fusion import rrf_fuse

    return rrf_fuse(rankings, k=k)


def test_formula_exata_com_k_60():
    result = dict(_fuse([["a", "b"], ["b", "c"]]))

    assert result["a"] == pytest.approx(1 / 61)
    assert result["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert result["c"] == pytest.approx(1 / 62)


def test_ordenacao_por_score_desc():
    result = _fuse([["a", "b"], ["b", "c"]])

    assert [doc for doc, _ in result] == ["b", "a", "c"]


def test_empate_de_score_desempata_por_id_asc():
    result = _fuse([["y"], ["x"]])

    assert [doc for doc, _ in result] == ["x", "y"]


def test_id_repetido_na_mesma_lista_conta_so_a_melhor_posicao():
    result = dict(_fuse([["a", "a", "b"]]))

    assert result["a"] == pytest.approx(1 / 61)
    assert len([doc for doc, _ in _fuse([["a", "a", "b"]])]) == 2


def test_vazio_devolve_lista_vazia():
    assert _fuse([]) == []
    assert _fuse([[]]) == []


def test_k_customizado_muda_a_formula():
    result = dict(_fuse([["a"]], k=10))

    assert result["a"] == pytest.approx(1 / 11)


@given(st.lists(IDS, unique=True, max_size=20))
def test_score_monotono_em_rank(ids: list[str]):
    fused = _fuse([ids])

    scores = [score for _, score in fused]
    assert scores == sorted(scores, reverse=True)
    assert [doc for doc, _ in fused] == ids


@given(st.lists(st.lists(IDS, unique=True, max_size=10), max_size=4))
def test_resultado_e_permutacao_dos_ids_de_entrada(rankings: list[list[str]]):
    fused = _fuse(rankings)

    ids = [doc for doc, _ in fused]
    assert len(ids) == len(set(ids))
    assert set(ids) == {doc for ranking in rankings for doc in ranking}


@given(st.lists(st.lists(IDS, unique=True, max_size=10), max_size=4))
def test_invariante_a_ordem_das_listas(rankings: list[list[str]]):
    forward = _fuse(rankings)
    backward = _fuse(list(reversed(rankings)))

    assert [doc for doc, _ in forward] == [doc for doc, _ in backward]
    for (_, a), (_, b) in zip(forward, backward, strict=True):
        assert a == pytest.approx(b)
