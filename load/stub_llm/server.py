"""Stub OpenAI-compatível para carga e caos (TASK-09-05). Só para teste local; nunca em produção.

Responde ao roteador com JSON de intenção e ao especialista com o protocolo do grafo:
`tool_call` de `get_order_status` quando a mensagem cita um pedido (O000123) e `final` depois do
resultado da ferramenta. `usage` traz tokens aproximados (caracteres / 4).

Ambiente (valores iniciais; `POST /admin/mode` muda em tempo de execução):
- LLM_STUB_LATENCY_MS (padrão 800) e LLM_STUB_JITTER_MS (padrão 100): espera por chamada;
- LLM_STUB_FAIL_RATE (0 a 1, padrão 0): fração de chamadas que devolvem 500;
- LLM_STUB_DOWN=1: toda chamada devolve 503 (provider fora do ar);
- LLM_STUB_PORT (padrão 8090) e LLM_STUB_HOST (padrão 127.0.0.1; 0.0.0.0 dentro de container).

Uso: uv run python load/stub_llm/server.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_ORDER = re.compile(r"\bO\d{6}\b")
_TOOL_RESULT = "<dados ferramenta>"
_ROUTER_MARK = "classifica a intenção"
_MAX_EVENTS = 50_000


class Mode:
    def __init__(self, env: dict[str, str]) -> None:
        self.latency_ms = float(env.get("LLM_STUB_LATENCY_MS", "800"))
        self.jitter_ms = float(env.get("LLM_STUB_JITTER_MS", "100"))
        self.fail_rate = float(env.get("LLM_STUB_FAIL_RATE", "0"))
        self.down = env.get("LLM_STUB_DOWN", "0") == "1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "jitter_ms": self.jitter_ms,
            "fail_rate": self.fail_rate,
            "down": self.down,
        }


class Stats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.counts: dict[str, int] = {}
        self.down_changes: list[tuple[float, bool]] = []
        self.rejected_at: list[float] = []

    def count(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def reject(self, kind: str) -> None:
        self.count(kind)
        if len(self.rejected_at) < _MAX_EVENTS:
            self.rejected_at.append(time.time())


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _last_user(messages: list[dict[str, Any]]) -> str:
    users = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
    return users[-1] if users else ""


def reply_for(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """(tipo, conteúdo) da resposta: `router`, `tool_call` ou `final`."""
    system = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    if _ROUTER_MARK in system:
        return "router", json.dumps({"intent": "order_status", "confidence": 0.95})
    if any(_TOOL_RESULT in str(m.get("content", "")) for m in messages):
        return "final", json.dumps(
            {"type": "final", "text": "Seu pedido está registrado. Algo mais?", "citations": []}
        )
    order = _ORDER.search(_last_user(messages))
    if order is not None:
        return "tool_call", json.dumps(
            {"type": "tool_call", "tool": "get_order_status", "arguments": {"order_id": order[0]}}
        )
    return "final", json.dumps(
        {"type": "final", "text": "Pode me passar o número do pedido?", "citations": []}
    )


def create_app(env: dict[str, str] | None = None) -> FastAPI:
    mode = Mode(dict(os.environ) if env is None else env)
    stats = Stats()
    app = FastAPI(title="stub-llm", docs_url=None, redoc_url=None)

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        messages: list[dict[str, Any]] = body.get("messages") or []
        delay = max(0.0, mode.latency_ms + random.uniform(-mode.jitter_ms, mode.jitter_ms))
        await asyncio.sleep(delay / 1000)
        if mode.down:
            stats.reject("down_503")
            return JSONResponse({"error": {"message": "stub fora do ar"}}, status_code=503)
        if mode.fail_rate and random.random() < mode.fail_rate:
            stats.reject("fail_500")
            return JSONResponse({"error": {"message": "falha injetada"}}, status_code=500)
        kind, content = reply_for(messages)
        stats.count(kind)
        prompt = " ".join(str(m.get("content", "")) for m in messages)
        return JSONResponse(
            {
                "id": f"stub-{time.time_ns()}",
                "object": "chat.completion",
                "model": str(body.get("model") or "stub"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": _tokens(prompt), "completion_tokens": _tokens(content)},
            }
        )

    @app.post("/admin/mode")
    async def set_mode(request: Request) -> dict[str, Any]:
        changes = await request.json()
        for key in ("latency_ms", "jitter_ms", "fail_rate"):
            if key in changes:
                setattr(mode, key, float(changes[key]))
        if "down" in changes and bool(changes["down"]) != mode.down:
            mode.down = bool(changes["down"])
            stats.down_changes.append((time.time(), mode.down))
        return mode.as_dict()

    @app.get("/admin/stats")
    async def get_stats() -> dict[str, Any]:
        return {
            "mode": mode.as_dict(),
            "counts": stats.counts,
            "down_changes": stats.down_changes,
            "rejected_at": stats.rejected_at,
        }

    @app.post("/admin/reset")
    async def reset() -> dict[str, str]:
        stats.reset()
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("LLM_STUB_HOST", "127.0.0.1"),
        port=int(os.environ.get("LLM_STUB_PORT", "8090")),
        log_level="warning",
    )
