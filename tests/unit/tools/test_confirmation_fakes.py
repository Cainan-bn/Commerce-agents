"""Os fakes de confirmação e idempotência precisam se comportar como os ports (ADR 0008/0011)."""

import pytest

from tests.fakes.confirmation import InMemoryIdempotencyRegistry, InMemoryTokenStore

pytestmark = pytest.mark.unit


async def test_token_e_de_uso_unico():
    store = InMemoryTokenStore()
    token = await store.issue("conv", "cancel_order", "digest", ttl_seconds=60)

    assert await store.consume(token, "conv", "cancel_order", "digest") is True
    assert await store.consume(token, "conv", "cancel_order", "digest") is False


async def test_token_vinculado_a_conversa_acao_e_digest_sem_consumir_em_falha_de_vinculo():
    store = InMemoryTokenStore()
    token = await store.issue("conv", "cancel_order", "digest", ttl_seconds=60)

    assert await store.consume(token, "outra", "cancel_order", "digest") is False
    assert await store.consume(token, "conv", "open_return", "digest") is False
    assert await store.consume(token, "conv", "cancel_order", "outro") is False
    assert await store.consume(token, "conv", "cancel_order", "digest") is True


async def test_token_expira_pelo_ttl():
    now = [1000.0]
    store = InMemoryTokenStore(clock=lambda: now[0])
    token = await store.issue("conv", "cancel_order", "digest", ttl_seconds=60)

    now[0] += 61

    assert await store.consume(token, "conv", "cancel_order", "digest") is False


async def test_token_desconhecido_e_recusado():
    store = InMemoryTokenStore()

    assert await store.consume("inexistente", "conv", "cancel_order", "digest") is False


async def test_registro_de_idempotencia_guarda_fingerprint_e_resultado():
    registry = InMemoryIdempotencyRegistry()

    assert await registry.get("k1") is None
    await registry.put("k1", "fp", '{"ok": true}')

    assert await registry.get("k1") == ("fp", '{"ok": true}')
