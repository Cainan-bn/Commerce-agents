"""Workers do pipeline: ``python -m commerce_agents.interfaces.worker [modo]``.

Modos: inbound, relay, sender, purge ou all.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.channels import (
    TOPIC_INBOUND,
    TOPIC_OUTBOUND,
    OutboundMessageReady,
)
from commerce_agents.application.dto.events import InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.messaging.bus import consume
from commerce_agents.infrastructure.messaging.senders import SendRejectedError
from commerce_agents.interfaces.composition import Settings, WorkerRuntime, build_worker, utcnow
from commerce_agents.interfaces.telemetry import configure_logging, setup_telemetry

logger = logging.getLogger(__name__)

MODES = ("inbound", "relay", "sender", "purge", "all")
_IDLE_SECONDS = 0.5
_ERROR_BACKOFF_SECONDS = 2.0


async def run_inbound(runtime: WorkerRuntime, settings: Settings) -> None:
    async def handler(event: StrictModel) -> None:
        if isinstance(event, InboundMessageReceived):
            await runtime.handle_inbound.execute(event)

    await consume(settings.kafka_bootstrap, TOPIC_INBOUND, "inbound-worker", handler)


async def run_relay(runtime: WorkerRuntime) -> None:
    while True:
        try:
            published = await runtime.relay.publish_pending()
        except Exception:
            logger.exception("relay do outbox falhou; nova tentativa em breve")
            await asyncio.sleep(_ERROR_BACKOFF_SECONDS)
            continue
        if published == 0:
            await asyncio.sleep(_IDLE_SECONDS)


async def run_sender(runtime: WorkerRuntime, settings: Settings) -> None:
    async def handler(event: StrictModel) -> None:
        # O canal web é entregue pelo hub de WebSocket do processo da API.
        if isinstance(event, OutboundMessageReady) and event.channel is not Channel.WEB:
            try:
                await runtime.sender.send(event)
            except SendRejectedError:
                logger.error("canal recusou a mensagem %s; descartada", event.message_id)

    await consume(settings.kafka_bootstrap, TOPIC_OUTBOUND, "sender-worker", handler)


async def run_purge(
    runtime: WorkerRuntime,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Purga tokens, idempotência e entregas além da retenção; uma falha não para as outras."""
    retention = timedelta(days=settings.retention_days)
    while True:
        cutoff = clock() - retention
        for purger in runtime.purgers:
            try:
                removed = await purger.purge(cutoff)
            except Exception:
                logger.exception(
                    "purga de %s falhou; nova tentativa no próximo ciclo", type(purger).__name__
                )
            else:
                logger.info("purga de %s removeu %d registros", type(purger).__name__, removed)
        await sleep(settings.purge_interval_s)


async def run(mode: str) -> None:
    settings = Settings.from_env()
    runtime = await build_worker(settings)
    jobs: dict[str, Callable[[], Awaitable[None]]] = {
        "inbound": lambda: run_inbound(runtime, settings),
        "relay": lambda: run_relay(runtime),
        "sender": lambda: run_sender(runtime, settings),
        "purge": lambda: run_purge(runtime, settings),
    }
    selected = list(jobs.values()) if mode == "all" else [jobs[mode]]
    try:
        await asyncio.gather(*(start() for start in selected))
    finally:
        await runtime.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="commerce_agents.interfaces.worker")
    parser.add_argument("mode", nargs="?", choices=MODES, default="all")
    args = parser.parse_args(argv)
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    setup_telemetry(os.environ)
    asyncio.run(run(args.mode))


if __name__ == "__main__":  # pragma: no cover
    main()
