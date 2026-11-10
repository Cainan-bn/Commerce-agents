"""Composição e workers: configuração por ambiente e laços com broker/ledger substituídos."""

import asyncio
from typing import Any

import pytest

from commerce_agents.application.dto.channels import OutboundMessageReady
from commerce_agents.application.dto.events import HandoffRequested, InboundMessageReceived
from commerce_agents.domain.conversation.channel import Channel
from commerce_agents.infrastructure.messaging.senders import SendRejectedError
from commerce_agents.interfaces import composition, worker
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit

ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",  # pragma: allowlist secret
    "WHATSAPP_APP_SECRET": "a",  # pragma: allowlist secret
    "PANEL_TOKEN": "t",  # pragma: allowlist secret
    "KAFKA_BOOTSTRAP": "broker:9092",
}


def test_settings_from_env_le_variaveis_e_aplica_defaults():
    settings = composition.Settings.from_env(ENV)

    assert settings.kafka_bootstrap == "broker:9092"
    assert settings.whatsapp_app_secret == "a"  # pragma: allowlist secret
    assert settings.web_session_secret == ""
    assert settings.store_base_url == composition.DEFAULT_STORE_BASE_URL
    assert composition.Settings.from_env({}).kafka_bootstrap == composition.DEFAULT_KAFKA_BOOTSTRAP


async def test_llm_nao_configurado_levanta_erro_explicito():
    with pytest.raises(RuntimeError, match="LLM não configurado"):
        await composition.UnconfiguredLLM().complete([], max_tokens=1)


async def test_notifier_publica_handoff_no_topico():
    published: list[Any] = []

    class Bus:
        async def publish(self, topic: str, key: str, event: Any) -> None:
            published.append((topic, key))

    await composition.BusHandoffNotifier(Bus()).notify(  # type: ignore[arg-type]
        HandoffRequested(
            conversation_id="web:a",
            reason="r",
            priority="normal",
            summary="s",
            requested_at=BASE_TIME,
        )
    )

    assert published == [("handoff.events", "web:a")]


async def test_build_api_liga_hub_e_consumidores_de_fundo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", ENV["DATABASE_URL"])
    handlers: dict[str, Any] = {}

    async def fake_consume(bootstrap: str, topic: str, group: str, handler: Any, **_: Any) -> None:
        handlers[topic] = handler

    monkeypatch.setattr(composition, "consume", fake_consume)
    deps = composition.build_api(composition.Settings.from_env(ENV))
    assert deps.background is not None
    await deps.background()

    sent: list[Any] = []

    class Socket:
        async def send_json(self, data: Any) -> None:
            sent.append(data)

    assert deps.hub is not None
    deps.hub.add_panel(Socket())
    deps.hub.add_conversation("web:a", Socket())
    await handlers["handoff.events"](
        HandoffRequested(
            conversation_id="web:a",
            reason="r",
            priority="normal",
            summary="s",
            requested_at=BASE_TIME,
        )
    )
    from commerce_agents.infrastructure.messaging.topics import PanelCustomerMessage

    await handlers["handoff.events"](PanelCustomerMessage(handoff_id="h", text="oi"))
    message = OutboundMessageReady(
        message_id="reply:1",
        conversation_id="web:a",
        channel=Channel.WEB,
        recipient_external_id="a",
        text="resposta",
        source="agent",
        created_at=BASE_TIME,
    )
    await handlers["outbound.messages"](message)
    await handlers["outbound.messages"](message.model_copy(update={"channel": Channel.WHATSAPP}))

    assert [e.get("type") for e in sent] == ["handoff_new", "handoff_message", "message"]


async def test_build_worker_monta_o_runtime_sem_conectar(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", ENV["DATABASE_URL"])
    runtime = await composition.build_worker(composition.Settings.from_env(ENV))

    await runtime.close()


class _Handle:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def execute(self, event: Any) -> None:
        self.events.append(event)


class _Sender:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[Any] = []

    async def send(self, message: Any) -> None:
        if self.fail:
            raise SendRejectedError("recusada")
        self.sent.append(message)


class _Relay:
    def __init__(self) -> None:
        self.calls = 0

    async def publish_pending(self) -> int:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("broker fora")
        return 0


def _runtime(handle: Any = None, sender: Any = None, relay: Any = None) -> Any:
    return type("R", (), {"handle_inbound": handle, "sender": sender, "relay": relay})()


def _inbound() -> InboundMessageReceived:
    return InboundMessageReceived(
        message_id="m1",
        conversation_id="web:a",
        channel=Channel.WEB,
        customer_external_id="a",
        text="oi",
        received_at=BASE_TIME,
    )


async def test_run_inbound_e_run_sender_delegam_aos_casos_de_uso(monkeypatch: pytest.MonkeyPatch):
    handlers: dict[str, Any] = {}

    async def fake_consume(bootstrap: str, topic: str, group: str, handler: Any, **_: Any) -> None:
        handlers[topic] = handler

    monkeypatch.setattr(worker, "consume", fake_consume)
    settings = composition.Settings.from_env(ENV)
    handle, sender = _Handle(), _Sender()
    await worker.run_inbound(_runtime(handle=handle), settings)
    await worker.run_sender(_runtime(sender=sender), settings)

    await handlers["inbound.messages"](_inbound())
    await handlers["inbound.messages"](
        HandoffRequested(
            conversation_id="c", reason="r", priority="low", summary="s", requested_at=BASE_TIME
        )
    )
    wa = OutboundMessageReady(
        message_id="reply:1",
        conversation_id="whatsapp:1",
        channel=Channel.WHATSAPP,
        recipient_external_id="1",
        text="x",
        source="agent",
        created_at=BASE_TIME,
    )
    await handlers["outbound.messages"](wa)
    await handlers["outbound.messages"](wa.model_copy(update={"channel": Channel.WEB}))
    sender.fail = True
    await handlers["outbound.messages"](wa)  # recusa do canal é descartada, sem lançar

    assert len(handle.events) == 1
    assert len(sender.sent) == 1


async def test_run_relay_sobrevive_a_falha_e_ociosidade(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker, "_ERROR_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(worker, "_IDLE_SECONDS", 0.0)
    relay = _Relay()

    task = asyncio.create_task(worker.run_relay(_runtime(relay=relay)))
    while relay.calls < 3:
        await asyncio.sleep(0)
    task.cancel()

    assert relay.calls >= 3


async def test_run_escolhe_os_jobs_do_modo_e_fecha_o_runtime(monkeypatch: pytest.MonkeyPatch):
    ran: list[str] = []
    closed: list[bool] = []

    class Runtime:
        async def close(self) -> None:
            closed.append(True)

    async def fake_build(settings: Any) -> Any:
        return Runtime()

    async def job(name: str) -> None:
        ran.append(name)

    monkeypatch.setattr(worker, "build_worker", fake_build)
    monkeypatch.setattr(worker, "run_inbound", lambda rt, st: job("inbound"))
    monkeypatch.setattr(worker, "run_relay", lambda rt: job("relay"))
    monkeypatch.setattr(worker, "run_sender", lambda rt, st: job("sender"))

    await worker.run("relay")
    await worker.run("all")

    assert ran == ["relay", "inbound", "relay", "sender"]
    assert closed == [True, True]


def test_main_interpreta_o_modo(monkeypatch: pytest.MonkeyPatch):
    modes: list[str] = []

    async def fake_run(mode: str) -> None:
        modes.append(mode)

    monkeypatch.setattr(worker, "run", fake_run)

    worker.main(["sender"])
    worker.main([])

    assert modes == ["sender", "all"]


def test_utcnow_devolve_datetime_com_fuso():
    assert composition.utcnow().tzinfo is not None


def test_llm_from_env_sem_modelo_usa_o_placeholder():
    assert isinstance(composition.llm_from_env({}), composition.UnconfiguredLLM)


def test_llm_from_env_com_modelo_usa_o_provider_configurado():
    from commerce_agents.infrastructure.llm.openai_compatible import OpenAICompatibleProvider

    api_key = "chave-de-teste"  # pragma: allowlist secret
    provider = composition.llm_from_env(
        {"LLM_PROVIDER": "openai-compatible", "LLM_MODEL": "m", "LLM_API_KEY": api_key}
    )

    # ADR 0017: o provider configurado vem envolvido no circuit breaker.
    assert isinstance(provider.inner, OpenAICompatibleProvider)  # type: ignore[attr-defined]
