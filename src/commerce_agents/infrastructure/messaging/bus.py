"""Barramento Redpanda/Kafka (aiokafka): publicação com acks=all e consumo com commit manual."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord, TopicPartition

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.infrastructure.messaging.topics import decode_event
from commerce_agents.infrastructure.telemetry import consumer_span, inject_headers

logger = logging.getLogger(__name__)

Handler = Callable[[StrictModel], Awaitable[None]]
_RETRY_DELAY_SECONDS = 1.0


class KafkaEventBus:
    """Implementa `EventBus`. A chave de partição é o `conversation_id` (ordem por conversa)."""

    def __init__(self, bootstrap: str) -> None:
        self._bootstrap = bootstrap
        self._producer: AIOKafkaProducer | None = None
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, key: str, event: StrictModel) -> None:
        producer = await self._ensure_started()
        # traceparent do contexto corrente: o consumidor continua o mesmo trace (ADR 0018).
        await producer.send_and_wait(
            topic, event.model_dump_json().encode(), key=key.encode(), headers=inject_headers()
        )

    async def close(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def _ensure_started(self) -> AIOKafkaProducer:
        async with self._lock:
            if self._producer is None:
                producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap, acks="all")
                await producer.start()
                self._producer = producer
            return self._producer


async def consume(
    bootstrap: str, topic: str, group: str, handler: Handler, *, from_latest: bool = False
) -> None:
    """Consome até ser cancelada. O offset só é confirmado após o handler concluir.

    Handler que falha não confirma: a mensagem é relida (at-least-once). Mensagem ilegível é
    descartada (confirmada), para não travar a partição.
    """
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=group,
        enable_auto_commit=False,
        auto_offset_reset="latest" if from_latest else "earliest",
    )
    await consumer.start()
    try:
        async for record in consumer:
            try:
                event = decode_event(record.value or b"")
            except ValueError:
                logger.error("mensagem ilegível em %s offset %s; descartada", topic, record.offset)
                await consumer.commit()
                continue
            try:
                with consumer_span(topic, record.headers):
                    await handler(event)
            except Exception:
                logger.exception(
                    "handler falhou em %s offset %s; será reentregue", topic, record.offset
                )
                consumer.seek(_partition(record), record.offset)
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                continue
            await consumer.commit()
    finally:
        await consumer.stop()


def _partition(record: ConsumerRecord[bytes, bytes]) -> TopicPartition:
    return TopicPartition(record.topic, record.partition)
