"""SqlConfirmationTokenStore contra Postgres real: mesma bateria dos fakes (ADR 0008/0011)."""

import asyncio
import hashlib
from typing import Any

import pytest
from sqlalchemy import text

from commerce_agents.infrastructure.persistence.database import create_session_factory
from tests.fakes.clock import FakeClock
from tests.integration.persistence.confirmation_helpers import new_engine_for

pytestmark = pytest.mark.integration

CONV = "conv-sql-1"
DIGEST = "d" * 64


def _store(factory: Any, clock: FakeClock) -> Any:
    from commerce_agents.infrastructure.persistence.token_store import SqlConfirmationTokenStore

    return SqlConfirmationTokenStore(factory, clock=clock)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


async def test_uso_unico(engine_and_factory, clock: FakeClock):
    _, factory = engine_and_factory
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    assert await store.consume(token, CONV, "cancel_order", DIGEST) is True
    assert await store.consume(token, CONV, "cancel_order", DIGEST) is False


async def test_expira_pelo_clock(engine_and_factory, clock: FakeClock):
    _, factory = engine_and_factory
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    clock.advance(301)

    assert await store.consume(token, CONV, "cancel_order", DIGEST) is False


async def test_vinculo_conversa_acao_digest_e_falha_nao_consome(
    engine_and_factory, clock: FakeClock
):
    _, factory = engine_and_factory
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    assert await store.consume(token, "outra", "cancel_order", DIGEST) is False
    assert await store.consume(token, CONV, "open_return", DIGEST) is False
    assert await store.consume(token, CONV, "cancel_order", "e" * 64) is False
    assert await store.consume(token, CONV, "cancel_order", DIGEST) is True


async def test_consumo_concorrente_tem_exatamente_um_vencedor(engine_and_factory, clock: FakeClock):
    _, factory = engine_and_factory
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    results = await asyncio.gather(
        *(store.consume(token, CONV, "cancel_order", DIGEST) for _ in range(10))
    )

    assert results.count(True) == 1


async def test_token_em_texto_nunca_e_gravado(engine_and_factory, clock: FakeClock):
    engine, factory = engine_and_factory
    store = _store(factory, clock)
    token = await store.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    async with engine.connect() as connection:
        rows = (await connection.execute(text("SELECT * FROM confirmation_tokens"))).all()

    assert rows, "o token emitido precisa estar persistido"
    stored_values = [str(value) for row in rows for value in row]
    assert all(token not in value for value in stored_values)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    assert any(token_hash in value for value in stored_values)


async def test_persiste_entre_instancias_e_engines(engine_and_factory, clock: FakeClock):
    engine, factory = engine_and_factory
    issuer = _store(factory, clock)
    token = await issuer.issue(CONV, "cancel_order", DIGEST, ttl_seconds=300)

    other_engine = new_engine_for(engine)
    try:
        other = _store(create_session_factory(other_engine), clock)

        assert await other.consume(token, CONV, "cancel_order", DIGEST) is True
    finally:
        await other_engine.dispose()
