"""SqlHandoffRepository (ADR 0014): create/get/ativo, claim atômico, close e mensagens em ordem."""

import asyncio
from datetime import UTC, datetime

import pytest

from commerce_agents.application.dto.channels import HandoffMessage, HandoffRecord, HandoffStatus
from tests.integration.channels.conftest import *  # noqa: F403

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _record(handoff_id: str = "h-1", conversation_id: str = "web:s1") -> HandoffRecord:
    return HandoffRecord(
        handoff_id=handoff_id,
        conversation_id=conversation_id,
        status=HandoffStatus.OPEN,
        reason="cliente pediu humano",
        priority="high",
        summary="resumo",
        created_at=AT,
    )


def _repo(factory):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.persistence.handoffs import SqlHandoffRepository

    return SqlHandoffRepository(factory)


async def test_create_get_e_ativo(channels_db):
    _, factory = channels_db
    repo = _repo(factory)

    await repo.create(_record())

    assert await repo.get("h-1") == _record()
    assert await repo.get_active("web:s1") == _record()
    assert [r.handoff_id for r in await repo.list_active()] == ["h-1"]


async def test_dez_claims_concorrentes_tem_um_vencedor(channels_db):
    _, factory = channels_db
    repo = _repo(factory)
    await repo.create(_record("h-race"))

    results = await asyncio.gather(*(repo.claim("h-race", f"agente-{n}", at=AT) for n in range(10)))

    assert sum(1 for r in results if r is not None) == 1
    winner = next(r for r in results if r is not None)
    assert winner.status is HandoffStatus.CLAIMED


async def test_close_encerra_e_some_dos_ativos(channels_db):
    _, factory = channels_db
    repo = _repo(factory)
    await repo.create(_record("h-close"))
    await repo.claim("h-close", "agente-ana", at=AT)

    closed = await repo.close("h-close", at=AT)

    assert closed is not None and closed.status is HandoffStatus.CLOSED
    assert await repo.get_active("web:s1") is None


async def test_mensagens_voltam_em_ordem(channels_db):
    _, factory = channels_db
    repo = _repo(factory)
    await repo.create(_record("h-msg"))
    for n in range(3):
        await repo.add_message(
            HandoffMessage(handoff_id="h-msg", author="customer", text=f"msg {n}", sent_at=AT)
        )

    messages = await repo.messages("h-msg")

    assert [m.text for m in messages] == ["msg 0", "msg 1", "msg 2"]
