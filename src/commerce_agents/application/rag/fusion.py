"""Reciprocal Rank Fusion (ADR 0005)."""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_RRF_K = 60


def rrf_fuse(
    rankings: Sequence[Sequence[str]], *, k: int = DEFAULT_RRF_K
) -> list[tuple[str, float]]:
    """Funde rankings: score = soma de 1/(k + posição); empate desempata por id crescente."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
