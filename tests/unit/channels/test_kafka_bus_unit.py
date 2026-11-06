"""KafkaEventBus e consume com aiokafka substituído: acks=all, commit após handler, reentrega."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from commerce_agents.application.dto.events import HandoffRequested
from commerce_agents.infrastructure.messaging import bus as bus_module
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit


def _event(n: int = 0) -> HandoffRequested:
    return HandoffRequested(
        conversation_id="web:a",
        reason=f"m{n}",
        priority="normal",
        summary="s",
        requested_at=BASE_TIME,
    )


class FakeProducer:
    instances: list["FakeProducer"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.stopped = False
        FakeProducer.instances.append(self)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.sent.append((topic, value, key))


class FakeConsumer:
    records: list[Any] = []
    last: "FakeConsumer | None" = None

    def __init__(self, *topics: str, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.commits = 0
        self.seeks: list[Any] = []
        self.stopped = False
        FakeConsumer.last = self

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True

    async def commit(self) -> None:
        self.commits += 1

    def seek(self, partition: Any, offset: int) -> None:
        self.seeks.append((partition, offset))

    def __aiter__(self) -> "FakeConsumer":
        self._iter = iter(list(FakeConsumer.records))
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


def _record(value: bytes, offset: int = 0) -> Any:
    return SimpleNamespace(value=value, offset=offset, topic="t", partition=0)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeProducer.instances.clear()
    monkeypatch.setattr(bus_module, "AIOKafkaProducer", FakeProducer)
    monkeypatch.setattr(bus_module, "AIOKafkaConsumer", FakeConsumer)


async def test_publish_usa_acks_all_chave_e_inicia_o_producer_uma_vez():
    bus = bus_module.KafkaEventBus("broker:9092")

    await bus.publish("t", "web:a", _event())
    await bus.publish("t", "web:a", _event(1))
    await bus.close()
    await bus.close()

    producer = FakeProducer.instances[0]
    assert len(FakeProducer.instances) == 1
    assert producer.kwargs["acks"] == "all"
    assert [key for _, _, key in producer.sent] == [b"web:a", b"web:a"]
    assert producer.stopped


async def test_consume_confirma_depois_do_handler_e_descarta_mensagem_ilegivel():
    FakeConsumer.records = [_record(b"lixo"), _record(_event().model_dump_json().encode(), 1)]
    seen: list[str] = []

    async def handler(event: Any) -> None:
        seen.append(event.reason)

    await bus_module.consume("b", "t", "g", handler, from_latest=True)

    consumer = FakeConsumer.last
    assert consumer is not None
    assert seen == ["m0"]
    assert consumer.commits == 2
    assert consumer.kwargs["auto_offset_reset"] == "latest"
    assert consumer.stopped


async def test_handler_que_falha_nao_confirma_e_volta_o_offset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bus_module, "_RETRY_DELAY_SECONDS", 0.0)
    FakeConsumer.records = [_record(_event().model_dump_json().encode(), 7)]

    async def failing(event: Any) -> None:
        raise RuntimeError("falhou")

    await asyncio.wait_for(bus_module.consume("b", "t", "g", failing), timeout=5)

    consumer = FakeConsumer.last
    assert consumer is not None
    assert consumer.commits == 0
    assert consumer.seeks[0][1] == 7
