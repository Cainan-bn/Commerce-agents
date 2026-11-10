"""Fixtures compartilhadas dos testes de avaliação."""

import pytest

from tests.fakes.shared_infra import Counts, install_counting_infra


@pytest.fixture
def infra(monkeypatch: pytest.MonkeyPatch) -> Counts:
    """Engine, embedder e retriever trocados por contadores (sem Postgres nem modelo)."""
    return install_counting_infra(monkeypatch)
