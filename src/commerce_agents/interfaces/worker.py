"""Workers do pipeline: ``python -m commerce_agents.interfaces.worker [modo]``.

Modos: inbound, relay, sender ou all.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

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
from commerce_agents.interfaces.composition import Settings, WorkerRuntime, build_worker

logger = logging.getLogger(__name__)

MODES = ("inbound", "relay", "sender", "all")
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


async def run(mode: str) -> None:
    settings = Settings.from_env()
    runtime = await build_worker(settings)
    jobs = {
        "inbound": [run_inbound(runtime, settings)],
        "relay": [run_relay(runtime)],
        "sender": [run_sender(runtime, settings)],
    }
    selected = [job for coros in jobs.values() for job in coros] if mode == "all" else jobs[mode]
    try:
        await asyncio.gather(*selected)
    finally:
        await runtime.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="commerce_agents.interfaces.worker")
    parser.add_argument("mode", nargs="?", choices=MODES, default="all")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run(args.mode))


if __name__ == "__main__":  # pragma: no cover
    main()
