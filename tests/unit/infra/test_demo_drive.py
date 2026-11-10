"""Driver da demonstração (scripts/demo_drive.py, ADR 0020, TASK-10-03a).

Contrato fixado (lógica separada do I/O):
- `load_conversations(path)` lê data/demo/conversations.yaml (id, title, customer_id, messages);
- `await run(conversations, transport, *, timeout_s, expect_no_miss) -> int` (código de saída):
  para cada conversa, `transport.start(customer_id)` cria a sessão (POST /demo/session); cada
  mensagem vai por `transport.send(session, text)` (POST /webhooks/web) e a próxima só sai depois
  de `transport.wait_reply(session, message_id, timeout_s)` devolver a resposta (WebSocket);
- sai != 0 se alguma mensagem ficar sem resposta (`None`); com `expect_no_miss`, também se alguma
  resposta for `DEMO_MISS_REPLY`;
- `main(argv) -> int` aceita `--api-url`, `--conversations`, `--timeout` e `--expect-no-miss`.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "scripts" / "demo_drive.py"
ROTEIRO = ROOT / "data" / "demo" / "conversations.yaml"

CONVERSAS = [
    {"id": "a", "title": "A", "customer_id": "C0001", "messages": ["a1", "a2"]},
    {"id": "b", "title": "B", "customer_id": "C0002", "messages": ["b1"]},
]


def _driver() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_drive", DRIVER)
    assert spec is not None and spec.loader is not None, f"{DRIVER} ausente"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    """Registra a ordem das chamadas; responde `replies[text]` (None = sem resposta)."""

    def __init__(self, replies: dict[str, str | None] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[tuple[str, ...]] = []
        self._pending: str | None = None

    async def start(self, customer_id: str) -> Any:
        self.calls.append(("start", customer_id))
        return {"customer_id": customer_id}

    async def send(self, session: Any, text: str) -> str:
        assert self._pending is None, "mensagem enviada antes da resposta da anterior"
        self.calls.append(("send", session["customer_id"], text))
        self._pending = text
        return f"m-{text}"

    async def wait_reply(self, session: Any, message_id: str, timeout_s: float) -> str | None:
        text = self._pending
        assert text is not None and message_id == f"m-{text}"
        self.calls.append(("wait", message_id, str(timeout_s)))
        self._pending = None
        return self.replies.get(text, f"resposta para {text}")


def test_carrega_o_roteiro_real():
    conversas = _driver().load_conversations(ROTEIRO)

    assert len(conversas) >= 5
    for conversa in conversas:
        assert conversa["customer_id"].startswith("C")
        assert conversa["messages"]


async def test_conversa_na_ordem_e_espera_cada_resposta():
    transport = FakeTransport()

    code = await _driver().run(CONVERSAS, transport, timeout_s=7.5, expect_no_miss=False)

    assert code == 0
    assert transport.calls == [
        ("start", "C0001"),
        ("send", "C0001", "a1"),
        ("wait", "m-a1", "7.5"),
        ("send", "C0001", "a2"),
        ("wait", "m-a2", "7.5"),
        ("start", "C0002"),
        ("send", "C0002", "b1"),
        ("wait", "m-b1", "7.5"),
    ]


async def test_mensagem_sem_resposta_sai_com_erro():
    transport = FakeTransport({"a2": None})

    code = await _driver().run(CONVERSAS, transport, timeout_s=1, expect_no_miss=False)

    assert code != 0


async def test_expect_no_miss_falha_com_o_aviso_de_demonstracao():
    from commerce_agents.infrastructure.llm.recorded import DEMO_MISS_REPLY

    driver = _driver()

    sem_flag = await driver.run(
        CONVERSAS, FakeTransport({"b1": DEMO_MISS_REPLY}), timeout_s=1, expect_no_miss=False
    )
    com_flag = await driver.run(
        CONVERSAS, FakeTransport({"b1": DEMO_MISS_REPLY}), timeout_s=1, expect_no_miss=True
    )

    assert sem_flag == 0
    assert com_flag != 0


def test_main_aceita_as_opcoes(monkeypatch: pytest.MonkeyPatch):
    driver = _driver()
    seen: dict[str, Any] = {}

    async def fake_run(conversations: Any, transport: Any, *, timeout_s: float, **kw: Any) -> int:
        seen.update(conversations=conversations, timeout_s=timeout_s, **kw)
        return 0

    monkeypatch.setattr(driver, "run", fake_run)

    code = driver.main(
        [
            "--api-url",
            "http://api.test:8000",
            "--conversations",
            str(ROTEIRO),
            "--timeout",
            "12",
            "--expect-no-miss",
        ]
    )

    assert code == 0
    assert seen["timeout_s"] == 12
    assert seen["expect_no_miss"] is True
    assert [c["id"] for c in seen["conversations"]] == [
        c["id"] for c in driver.load_conversations(ROTEIRO)
    ]
