"""Purga de tokens de confirmação e registros de idempotência (Fase 09)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from tests.fakes.clock import FakeClock

pytestmark = pytest.mark.integration

CONV = "conv-purge-1"
DIGEST = "d" * 64
DAY = 24 * 3600


def _store(factory: Any, clock: FakeClock) -> Any:
    from commerce_agents.infrastructure.persistence.token_store import SqlConfirmationTokenStore

    return SqlConfirmationTokenStore(factory, clock=clock)


def _registry(factory: Any) -> Any:
    from commerce_agents.infrastructure.persistence.idempotency import SqlIdempotencyRegistry

    return SqlIdempotencyRegistry(factory)


async def _count(engine: Any, table: str) -> int:
    async with engine.connect() as connection:
        return int((await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def test_purge_de_tokens_apaga_expirados_antes_do_corte(engine_and_factory):
    engine, factory = engine_and_factory
    clock = FakeClock()
    store = _store(factory, clock)
    expired = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)
    clock.advance(10 * DAY)

    removed = await store.purge(clock() - timedelta(days=1))

    assert removed == 1
    assert await _count(engine, "confirmation_tokens") == 0
    assert await store.consume(expired, CONV, "cancel_order", DIGEST) is False


async def test_purge_de_tokens_apaga_usados_antes_do_corte(engine_and_factory):
    engine, factory = engine_and_factory
    clock = FakeClock()
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)
    assert await store.consume(token, CONV, "cancel_order", DIGEST) is True

    # Corte além do expires_at: o token usado sai mesmo sem ter expirado ainda.
    removed = await store.purge(clock() + timedelta(seconds=600))

    assert removed == 1
    assert await _count(engine, "confirmation_tokens") == 0


async def test_purge_de_tokens_mantem_expirados_depois_do_corte(engine_and_factory):
    engine, factory = engine_and_factory
    clock = FakeClock()
    store = _store(factory, clock)
    await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)
    clock.advance(DAY)

    removed = await store.purge(clock() - timedelta(days=30))

    assert removed == 0
    assert await _count(engine, "confirmation_tokens") == 1


async def test_token_valido_e_nao_usado_nunca_e_apagado(engine_and_factory):
    engine, factory = engine_and_factory
    clock = FakeClock()
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    # Mesmo com corte no futuro, além do expires_at, o token ainda vale.
    removed = await store.purge(clock() + timedelta(days=365))

    assert removed == 0
    assert await _count(engine, "confirmation_tokens") == 1
    assert await store.consume(token, CONV, "cancel_order", DIGEST) is True


async def test_purge_de_tokens_devolve_quantos_apagou(engine_and_factory):
    engine, factory = engine_and_factory
    clock = FakeClock()
    store = _store(factory, clock)
    for _ in range(3):
        await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)
    clock.advance(10 * DAY)
    keep = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    removed = await store.purge(clock() - timedelta(days=1))

    assert removed == 3
    assert await _count(engine, "confirmation_tokens") == 1
    assert await store.consume(keep, CONV, "cancel_order", DIGEST) is True


async def test_purge_de_idempotencia_por_created_at(engine_and_factory):
    engine, factory = engine_and_factory
    registry = _registry(factory)
    await registry.put("idem-purge-000001", "fp-1", '{"ok": true}')
    await registry.put("idem-purge-000002", "fp-2", '{"ok": true}')
    now = datetime.now(UTC)

    assert await registry.purge(now - timedelta(days=1)) == 0
    assert await registry.get("idem-purge-000001") == ("fp-1", '{"ok": true}')

    assert await registry.purge(now + timedelta(days=1)) == 2
    assert await registry.get("idem-purge-000001") is None
    assert await _count(engine, "idempotency_records") == 0
