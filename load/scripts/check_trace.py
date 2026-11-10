"""Verificação ponta a ponta do trace de UMA mensagem (TASK-09-05, ADR 0018).

Envia uma mensagem web com o sistema ocioso, espera a resposta pelo WebSocket e lista, pela API
do Jaeger, todos os traces do serviço na janela do envio com os spans de cada um. Conclui se a
mensagem gerou um único trace com os saltos esperados ou em quais saltos o contexto se perdeu.
Não conserta nada: só mede. Uso: ver load/run.sh (cenário trace).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import websockets

from commerce_agents.interfaces.webhooks.web import sign_web_session

# Saltos esperados, na ordem do caminho da mensagem.
EXPECTED = (
    ("webhook (API)", lambda name: name.startswith(("POST", "/webhooks", "webhook"))),
    ("worker: inbound.messages", lambda name: name == "inbound.messages process"),
    ("conversation.turn", lambda name: name == "conversation.turn"),
    ("llm.complete", lambda name: name == "llm.complete"),
    ("tool.invoke", lambda name: name == "tool.invoke"),
    ("outbox.publish", lambda name: name == "outbox.publish"),
    ("consumidor: outbound.messages", lambda name: name == "outbound.messages process"),
    ("envio: channel.send", lambda name: name == "channel.send"),
)


async def send_and_wait(base: str, secret: str, customer: str, text: str) -> dict[str, Any]:
    session_id = f"trace-{uuid.uuid4().hex[:12]}"
    message_id = f"trace-msg-{uuid.uuid4().hex[:12]}"
    token = sign_web_session(secret, session_id, customer, datetime.now(UTC) + timedelta(hours=1))
    conversation_id = f"web:{session_id}"
    ws_url = base.replace("http", "ws", 1)
    url = f"{ws_url}/ws/web/{quote(conversation_id, safe='')}?token={quote(token, safe='')}"
    async with websockets.connect(url) as socket, httpx.AsyncClient(base_url=base) as client:
        sent_at = time.time()
        response = await client.post(
            "/webhooks/web",
            json={"session_id": session_id, "message_id": message_id, "text": text},
            headers={"X-Web-Session": token},
        )
        response.raise_for_status()
        reply = None
        while reply is None:
            event = json.loads(await asyncio.wait_for(socket.recv(), timeout=60))
            if event.get("message_id") == f"reply:{message_id}":
                reply = event
    return {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "sent_at": sent_at,
        "replied_after_s": round(time.time() - sent_at, 3),
        "reply_source": reply.get("source"),
    }


def jaeger_traces(jaeger: str, service: str, start: float, end: float) -> list[dict[str, Any]]:
    params = {
        "service": service,
        "start": int(start * 1_000_000),
        "end": int(end * 1_000_000),
        "limit": 200,
    }
    response = httpx.get(f"{jaeger}/api/traces", params=params, timeout=30)
    response.raise_for_status()
    return list(response.json()["data"])


def summarize(trace: dict[str, Any]) -> dict[str, Any]:
    spans = trace["spans"]
    tags: dict[str, list[str]] = {}
    for span in spans:
        for tag in span.get("tags", []):
            if tag["key"] in ("conversation_id", "message_id"):
                values = tags.setdefault(tag["key"], [])
                if tag["value"] not in values:
                    values.append(tag["value"])
    roots = [s["operationName"] for s in spans if not s.get("references")]
    return {
        "trace_id": trace["traceID"],
        "spans": sorted({s["operationName"] for s in spans}),
        "raizes": roots,
        "tags": tags,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--jaeger", default=os.environ.get("JAEGER_URL", "http://localhost:16686"))
    parser.add_argument("--service", default=os.environ.get("OTEL_SERVICE_NAME", "commerce-agents"))
    parser.add_argument("--customer", default="C0167")
    parser.add_argument("--order", default="O000001")
    parser.add_argument("--wait-s", type=float, default=15.0)
    parser.add_argument(
        "--probe-only", action="store_true", help="só envia e espera a resposta (aquecimento)"
    )
    args = parser.parse_args()

    sent = asyncio.run(
        send_and_wait(
            args.base_url,
            os.environ["WEB_SESSION_SECRET"],
            args.customer,
            f"onde está meu pedido {args.order}?",
        )
    )
    if args.probe_only:
        print(json.dumps(sent, ensure_ascii=False))
        return
    time.sleep(args.wait_s)  # BatchSpanProcessor exporta a cada 5 s
    traces = [
        summarize(t)
        for t in jaeger_traces(args.jaeger, args.service, sent["sent_at"] - 2, time.time())
    ]
    all_names = {name for t in traces for name in t["spans"]}
    # Só os traces desta mensagem (a janela pode trazer o aquecimento e a conexão WebSocket).
    mine = [
        t
        for t in traces
        if sent["conversation_id"] in t["tags"].get("conversation_id", [])
        or sent["message_id"] in t["tags"].get("message_id", [])
    ]
    hops = {
        label: [t["trace_id"] for t in mine if any(match(n) for n in t["spans"])]
        for label, match in EXPECTED
    }
    found = [label for label, ids in hops.items() if ids]
    trace_ids = {tid for ids in hops.values() for tid in ids}
    result = {
        "envio": sent,
        "traces_na_janela": len(traces),
        "traces_da_mensagem": [t["trace_id"] for t in mine],
        "traces": traces,
        "saltos": hops,
        "saltos_presentes": found,
        "saltos_ausentes": [label for label, ids in hops.items() if not ids],
        "um_unico_trace": len(trace_ids) == 1 and len(found) == len(EXPECTED),
        "spans_vistos": sorted(all_names),
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
