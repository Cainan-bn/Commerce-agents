"""Driver da demonstração (ADR 0020): conversa pelo canal web real com o roteiro de
data/demo/conversations.yaml.

Para cada conversa cria a sessão (POST /demo/session), envia cada mensagem pelo webhook web e
espera a resposta no WebSocket da conversa antes da próxima. Serve para gravar o cassete da
demonstração pelo caminho real (`make demo-record`) e para conferi-lo (`make demo-verify`).

Uso: uv run python scripts/demo_drive.py [--api-url URL] [--conversations ARQ] [--timeout S]
                                         [--expect-no-miss]
Sai com código != 0 se alguma mensagem ficar sem resposta ou, com --expect-no-miss, se alguma
resposta for o aviso de fora do roteiro (DEMO_MISS_REPLY).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import websockets
import yaml

from commerce_agents.infrastructure.llm.recorded import DEMO_MISS_REPLY

DEFAULT_CONVERSATIONS = Path(__file__).resolve().parents[1] / "data" / "demo" / "conversations.yaml"


class Transport(Protocol):
    async def start(self, customer_id: str) -> Any: ...

    async def send(self, session: Any, text: str) -> str: ...

    async def wait_reply(self, session: Any, message_id: str, timeout_s: float) -> str | None: ...


def load_conversations(path: Path | str) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [
        {
            "id": str(c["id"]),
            "title": str(c["title"]),
            "customer_id": str(c["customer_id"]),
            "messages": [str(m) for m in c["messages"]],
        }
        for c in data.get("conversations", [])
    ]


def _log(text: str) -> None:
    print(text, flush=True)


async def run(
    conversations: list[dict[str, Any]],
    transport: Transport,
    *,
    timeout_s: float,
    expect_no_miss: bool,
) -> int:
    """Percorre o roteiro; devolve o código de saída (0 = toda mensagem respondida)."""
    failures = 0
    for conversation in conversations:
        _log(f"== {conversation['id']}: {conversation['title']} ({conversation['customer_id']})")
        session = await transport.start(conversation["customer_id"])
        for text in conversation["messages"]:
            message_id = await transport.send(session, text)
            reply = await transport.wait_reply(session, message_id, timeout_s)
            if reply is None:
                failures += 1
                _log(f"   cliente: {text}\n   SEM RESPOSTA em {timeout_s:g} s")
                continue
            miss = reply == DEMO_MISS_REPLY
            if miss and expect_no_miss:
                failures += 1
            _log(f"   cliente: {text}\n   agente{' (FORA DO ROTEIRO)' if miss else ''}: {reply}")
    _log("ok: todas as mensagens responderam" if failures == 0 else f"falhas: {failures}")
    return 0 if failures == 0 else 1


class HttpTransport:
    """Transporte real: POST /demo/session, POST /webhooks/web e WebSocket da conversa."""

    def __init__(self, api_url: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._sockets: list[Any] = []

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._api_url, timeout=30.0)
        return self._client

    async def start(self, customer_id: str) -> dict[str, Any]:
        response = await self._http().post("/demo/session", json={"customer_id": customer_id})
        response.raise_for_status()
        session: dict[str, Any] = response.json()
        ws_path = session["ws_path"]
        if "token=" not in ws_path:
            ws_path += ("&" if "?" in ws_path else "?") + f"token={quote(session['token'])}"
        ws_url = self._api_url.replace("http", "ws", 1) + ws_path
        socket = await websockets.connect(ws_url)
        self._sockets.append(socket)
        session["socket"] = socket
        return session

    async def send(self, session: dict[str, Any], text: str) -> str:
        message_id = f"demo-{uuid.uuid4().hex[:12]}"
        response = await self._http().post(
            "/webhooks/web",
            json={
                "session_id": session["conversation_id"].removeprefix("web:"),
                "message_id": message_id,
                "text": text,
            },
            headers={"X-Web-Session": session["token"]},
        )
        response.raise_for_status()
        return message_id

    async def wait_reply(
        self, session: dict[str, Any], message_id: str, timeout_s: float
    ) -> str | None:
        deadline = time.monotonic() + timeout_s
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                raw = await asyncio.wait_for(session["socket"].recv(), timeout=remaining)
            except (TimeoutError, websockets.ConnectionClosed):
                return None
            event = json.loads(raw)
            if event.get("type") == "message" and event.get("message_id") == f"reply:{message_id}":
                return str(event.get("text", ""))
        return None

    async def aclose(self) -> None:
        for socket in self._sockets:
            await socket.close()
        if self._client is not None:
            await self._client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo_drive", description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--conversations", type=Path, default=DEFAULT_CONVERSATIONS)
    parser.add_argument("--timeout", type=float, default=60.0, help="espera por resposta (s)")
    parser.add_argument("--expect-no-miss", action="store_true")
    args = parser.parse_args(argv)

    async def drive() -> int:
        transport = HttpTransport(args.api_url)
        try:
            return await run(
                load_conversations(args.conversations),
                transport,
                timeout_s=args.timeout,
                expect_no_miss=args.expect_no_miss,
            )
        finally:
            await transport.aclose()

    return asyncio.run(drive())


if __name__ == "__main__":
    sys.exit(main())
