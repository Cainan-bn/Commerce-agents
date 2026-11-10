"""Relógio controlável para expiração de propostas e tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BASE_TIME = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = BASE_TIME) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeMonotonic:
    """Relógio monotônico em segundos (como `time.monotonic`), avançado à mão pelo teste."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
