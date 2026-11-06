"""SqlIdempotencyRegistry contra Postgres real (ADR 0011: PENDENTE e fingerprint)."""

from typing import Any

import pytest

from commerce_agents.infrastructure.persistence.database import create_session_factory
from tests.integration.persistence.confirmation_helpers import new_engine_for

pytestmark = pytest.mark.integration

PENDING = "__pending__"


def _registry(factory: Any) -> Any:
    from commerce_agents.infrastructure.persistence.idempotency import SqlIdempotencyRegistry

    return SqlIdempotencyRegistry(factory)


async def test_get_ausente_e_put_depois_get(engine_and_factory):
    _, factory = engine_and_factory
    registry = _registry(factory)

    assert await registry.get("idem-sql-000001") is None
    await registry.put("idem-sql-000001", "fp-1", '{"ok": true}')

    assert await registry.get("idem-sql-000001") == ("fp-1", '{"ok": true}')


async def test_fingerprint_diferente_nao_sobrescreve(engine_and_factory):
    _, factory = engine_and_factory
    registry = _registry(factory)
    await registry.put("idem-sql-000002", "fp-original", '{"ok": true}')

    await registry.put("idem-sql-000002", "fp-outro", '{"ok": false}')

    assert await registry.get("idem-sql-000002") == ("fp-original", '{"ok": true}')


async def test_pendente_pode_ser_sobrescrito_pelo_resultado(engine_and_factory):
    _, factory = engine_and_factory
    registry = _registry(factory)
    await registry.put("idem-sql-000003", "fp-1", PENDING)

    await registry.put("idem-sql-000003", "fp-1", '{"ok": true}')

    assert await registry.get("idem-sql-000003") == ("fp-1", '{"ok": true}')


async def test_persiste_entre_instancias_e_engines(engine_and_factory):
    engine, factory = engine_and_factory
    await _registry(factory).put("idem-sql-000004", "fp-1", '{"ok": true}')

    other_engine = new_engine_for(engine)
    try:
        other = _registry(create_session_factory(other_engine))

        assert await other.get("idem-sql-000004") == ("fp-1", '{"ok": true}')
    finally:
        await other_engine.dispose()
