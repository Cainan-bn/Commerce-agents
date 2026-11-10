"""Token de sessão fora dos logs de acesso (ADR 0013/0014, TASK-10-07a).

O navegador não manda header no WebSocket, então o token da sessão web vai na query
(`/ws/web/<id>?token=...`) e o uvicorn o logava inteiro. Contrato fixado:
- `commerce_agents.interfaces.log_redaction.RedactQueryTokens`: filtro de logging que troca o
  valor dos parâmetros de query `token`, `hub.verify_token` e `access_token` (sem diferenciar
  maiúsculas) por `***` em `msg` e `args`, sem mexer no resto da linha;
- `commerce_agents.interfaces.telemetry.configure_logging()` (chamado pela API e pelo worker)
  instala o filtro em `uvicorn.access` e `uvicorn.error`; chamar 2x não duplica;
- guarda: nenhum logger da aplicação registra o header `X-Web-Session` nem o `PANEL_TOKEN`.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any

import httpx
import pytest

from commerce_agents.interfaces.webhooks.web import sign_web_session
from tests.fakes.clock import BASE_TIME

pytestmark = pytest.mark.unit

SEGREDO = "SegredoDaSessao.abc123def456"  # pragma: allowlist secret
VERIFY = "VerifyTokenDaMeta987"  # pragma: allowlist secret
ACCESS = "AccessTokenGraph555"  # pragma: allowlist secret
WEB_SECRET = "web-secret-redacao"  # pragma: allowlist secret
PANEL_TOKEN = "PainelTokenSecreto321"  # pragma: allowlist secret
UVICORN_LOGGERS = ("uvicorn.access", "uvicorn.error")


def _configure() -> None:
    from commerce_agents.interfaces.telemetry import configure_logging

    configure_logging("INFO")


def _filter_type() -> Any:
    from commerce_agents.interfaces.log_redaction import RedactQueryTokens

    return RedactQueryTokens


def _record(logger: str, msg: str, args: tuple[Any, ...]) -> logging.LogRecord:
    return logging.LogRecord(logger, logging.INFO, __file__, 1, msg, args, None)


def _apply(record: logging.LogRecord) -> str:
    """Passa o registro pelos filtros do logger de destino, como o `Logger.handle` faz."""
    logger = logging.getLogger(record.name)
    assert logger.filter(record), "o filtro não pode descartar a linha"
    return record.getMessage()


# ------------------------------------------------------------------ formatos exatos do uvicorn


def test_linha_de_acesso_http_esconde_o_token_e_mantem_o_resto():
    _configure()
    record = _record(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:5555",
            "GET",
            f"/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=7",
            "1.1",
            200,
        ),
    )

    line = _apply(record)

    assert VERIFY not in line
    assert line == (
        '127.0.0.1:5555 - "GET /webhooks/whatsapp?hub.mode=subscribe'
        '&hub.verify_token=***&hub.challenge=7 HTTP/1.1" 200'
    )


@pytest.mark.parametrize(
    ("msg", "extra"),
    [
        ('%s - "WebSocket %s" [accepted]', ()),
        ('%s - "WebSocket %s" 403', ()),
        ('%s - "WebSocket %s" %d', (500,)),
    ],
)
def test_linhas_de_websocket_escondem_o_token(msg: str, extra: tuple[Any, ...]):
    _configure()
    path = f"/ws/web/web%3Asessao-1?token={SEGREDO}"
    record = _record("uvicorn.error", msg, ("127.0.0.1:5555", path, *extra))

    line = _apply(record)

    assert SEGREDO not in line
    assert "/ws/web/web%3Asessao-1?token=***" in line


@pytest.mark.parametrize(
    "query",
    [
        f"?TOKEN={SEGREDO}",
        f"?x=1&Token={SEGREDO}&y=2",
        f"?access_token={ACCESS}",
        f"?ACCESS_TOKEN={ACCESS}&z=3",
        f"?Hub.Verify_Token={VERIFY}",
    ],
)
def test_parametros_sensiveis_sem_diferenciar_maiusculas(query: str):
    _configure()
    args = ("c", "GET", f"/x{query}", "1.1", 200)
    record = _record("uvicorn.access", '%s - "%s %s HTTP/%s" %d', args)

    line = _apply(record)

    for secret in (SEGREDO, ACCESS, VERIFY):
        assert secret not in line
    assert "=***" in line


def test_parametro_parecido_nao_e_alterado():
    _configure()
    path = "/x?tokenizer=abc&mytoken=def&page=2"
    record = _record("uvicorn.access", '%s - "%s %s HTTP/%s" %d', ("c", "GET", path, "1.1", 200))

    assert _apply(record) == f'c - "GET {path} HTTP/1.1" 200'


def test_token_na_propria_mensagem_tambem_e_escondido():
    _configure()
    record = _record("uvicorn.error", f"falha em /ws/web/x?token={SEGREDO}", ())

    line = _apply(record)

    assert SEGREDO not in line
    assert "?token=***" in line


# ------------------------------------------------------------------ instalação


def test_configure_logging_instala_nos_loggers_do_uvicorn_sem_duplicar():
    redact = _filter_type()

    _configure()
    _configure()

    for name in UVICORN_LOGGERS:
        filtros = [f for f in logging.getLogger(name).filters if isinstance(f, redact)]
        assert len(filtros) == 1, name


# ------------------------------------------------------------------ servidor real


def _deps() -> Any:
    from commerce_agents.application.use_cases.request_handoff import (
        ClaimHandoff,
        CloseHandoff,
        HumanReply,
    )
    from commerce_agents.infrastructure.messaging.hub import PanelHub
    from commerce_agents.interfaces.api import ApiDeps
    from tests.fakes.channels import InMemoryConversationRepository, InMemoryHandoffRepository
    from tests.fakes.clock import FakeClock

    class Bus:
        async def publish(self, topic: str, key: str, event: Any) -> None:
            return None

    handoffs = InMemoryHandoffRepository()
    clock = FakeClock()
    return ApiDeps(
        bus=Bus(),
        handoffs=handoffs,
        claim=ClaimHandoff(handoffs, clock=clock),
        reply=HumanReply(handoffs, clock=clock),
        close=CloseHandoff(handoffs, InMemoryConversationRepository(), clock=clock),
        hub=PanelHub(),
        whatsapp_app_secret="x",  # pragma: allowlist secret
        whatsapp_verify_token=VERIFY,
        instagram_app_secret="y",  # pragma: allowlist secret
        instagram_verify_token="w",  # pragma: allowlist secret
        web_session_secret=WEB_SECRET,
        panel_token=PANEL_TOKEN,
        clock=clock,
    )


async def test_uvicorn_real_nao_loga_o_token_do_websocket_nem_o_verify_token(
    caplog: pytest.LogCaptureFixture,
):
    import uvicorn
    import websockets

    from commerce_agents.interfaces.api import create_app

    # Como no uvicorn real: o LOGGING_CONFIG do uvicorn é aplicado e depois o app é importado
    # (interfaces/main.py chama configure_logging).
    config = uvicorn.Config(create_app(_deps()), host="127.0.0.1", port=0, lifespan="off")
    _configure()
    for name in UVICORN_LOGGERS:
        logging.getLogger(name).addHandler(caplog.handler)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        token = sign_web_session(WEB_SECRET, "s1", "C0001", BASE_TIME + timedelta(hours=1))
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/web/web%3As1?token={token}"):
            pass
        async with httpx.AsyncClient() as client:
            await client.get(
                f"http://127.0.0.1:{port}/webhooks/whatsapp",
                params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "7"},
            )
        await asyncio.sleep(0.1)
    finally:
        server.should_exit = True
        await task
        for name in UVICORN_LOGGERS:
            logging.getLogger(name).removeHandler(caplog.handler)

    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "WebSocket /ws/web/web%3As1?token=***" in texto
    assert "hub.verify_token=***" in texto
    assert token not in texto
    assert VERIFY not in texto


# ------------------------------------------------------------------ guarda da aplicação


async def test_rotas_web_e_painel_nao_logam_sessao_nem_token_do_painel(
    caplog: pytest.LogCaptureFixture,
):
    from commerce_agents.interfaces.api import create_app

    app = create_app(_deps())
    token = sign_web_session(WEB_SECRET, "s2", "C0001", BASE_TIME + timedelta(hours=1))
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            await client.post(
                "/webhooks/web",
                json={"session_id": "s2", "message_id": "m1", "text": "oi"},
                headers={"X-Web-Session": token},
            )
            await client.post(
                "/webhooks/web",
                json={"session_id": "s2", "message_id": "m2", "text": "oi"},
                headers={"X-Web-Session": token + "adulterado"},
            )
            await client.get("/api/handoffs", headers={"Authorization": f"Bearer {PANEL_TOKEN}"})
            await client.get("/api/handoffs", headers={"Authorization": "Bearer errado"})

    texto = "\n".join(f"{r.name} {r.getMessage()} {r.exc_text or ''}" for r in caplog.records)
    assert token not in texto
    assert PANEL_TOKEN not in texto
