"""Purga periódica do worker: intervalo e retenção por ambiente, relógio e sleep falsos."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import pytest

from commerce_agents.interfaces import composition, worker
from tests.fakes.clock import BASE_TIME, FakeClock

pytestmark = pytest.mark.unit


class _Purger:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls: list[datetime] = []

    async def purge(self, older_than: datetime) -> int:
        self.calls.append(older_than)
        if self.fail:
            raise ConnectionError(f"{self.name} fora")
        return 1


class _Sleep:
    """Registra as esperas, avança o relógio e cancela o laço após `rounds` esperas."""

    def __init__(self, clock: FakeClock, rounds: int) -> None:
        self.clock = clock
        self.rounds = rounds
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.clock.advance(seconds)
        if len(self.waits) >= self.rounds:
            raise asyncio.CancelledError


def _runtime(*purgers: _Purger) -> Any:
    return type("R", (), {"purgers": tuple(purgers)})()


def _settings(env: dict[str, str] | None = None) -> composition.Settings:
    return composition.Settings.from_env(env or {})


def test_settings_de_purga_tem_defaults():
    settings = _settings()

    assert settings.purge_interval_s == 3600
    assert settings.retention_days == 30


def test_settings_de_purga_le_o_ambiente():
    settings = _settings({"PURGE_INTERVAL_S": "60", "RETENTION_DAYS": "7"})

    assert settings.purge_interval_s == 60
    assert settings.retention_days == 7


async def test_purga_chama_as_tres_purgas_com_corte_pela_retencao():
    clock = FakeClock()
    sleep = _Sleep(clock, rounds=1)
    purgers = (_Purger("tokens"), _Purger("idempotencia"), _Purger("entregas"))

    with pytest.raises(asyncio.CancelledError):
        await worker.run_purge(_runtime(*purgers), _settings(), clock=clock, sleep=sleep)

    for purger in purgers:
        assert purger.calls == [BASE_TIME - timedelta(days=30)]


async def test_purga_repete_no_intervalo_configurado():
    clock = FakeClock()
    sleep = _Sleep(clock, rounds=3)
    purger = _Purger("tokens")
    settings = _settings({"PURGE_INTERVAL_S": "60", "RETENTION_DAYS": "7"})

    with pytest.raises(asyncio.CancelledError):
        await worker.run_purge(_runtime(purger), settings, clock=clock, sleep=sleep)

    assert sleep.waits == [60, 60, 60]
    cutoff = BASE_TIME - timedelta(days=7)
    assert purger.calls == [cutoff + timedelta(seconds=60 * i) for i in range(3)]


async def test_erro_numa_purga_nao_derruba_o_worker_e_e_logado(caplog: pytest.LogCaptureFixture):
    clock = FakeClock()
    sleep = _Sleep(clock, rounds=2)
    broken, healthy = _Purger("tokens", fail=True), _Purger("entregas")

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await worker.run_purge(_runtime(broken, healthy), _settings(), clock=clock, sleep=sleep)

    assert len(broken.calls) == 2
    assert len(healthy.calls) == 2
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_modo_purge_existe():
    assert "purge" in worker.MODES
