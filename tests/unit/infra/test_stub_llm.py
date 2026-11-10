"""Stub OpenAI-compatível da carga (load/stub_llm): protocolo do grafo, latência e falhas."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

SERVER = Path(__file__).resolve().parents[3] / "load" / "stub_llm" / "server.py"
NO_DELAY = {"LLM_STUB_LATENCY_MS": "0", "LLM_STUB_JITTER_MS": "0"}


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stub_llm_server", SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(**env: str) -> TestClient:
    return TestClient(_module().create_app({**NO_DELAY, **env}))


def _chat(client: TestClient, messages: list[dict[str, str]]) -> Any:
    return client.post("/v1/chat/completions", json={"model": "stub-model", "messages": messages})


def _content(response: Any) -> dict[str, Any]:
    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["completion_tokens"] > 0
    return dict(json.loads(body["choices"][0]["message"]["content"]))


ROUTER = {"role": "system", "content": "Você classifica a intenção de uma mensagem de cliente."}
AGENT = {"role": "system", "content": "Você é o agente de pedidos."}


def test_roteador_recebe_json_de_intencao_valido():
    from commerce_agents.application.dto.agents import Intent

    decision = _content(_chat(_client(), [ROUTER, {"role": "user", "content": "e o O000001?"}]))

    assert Intent(decision["intent"])
    assert 0 <= decision["confidence"] <= 1


def test_especialista_pede_a_ferramenta_e_depois_responde():
    client = _client()
    user = {"role": "user", "content": "<dados cliente>onde está o pedido O000123?</dados>"}

    call = _content(_chat(client, [AGENT, user]))
    tool = {"role": "user", "content": '<dados ferramenta>{"status": "paid"}</dados>'}
    final = _content(_chat(client, [AGENT, user, {"role": "assistant", "content": "x"}, tool]))

    assert call == {
        "type": "tool_call",
        "tool": "get_order_status",
        "arguments": {"order_id": "O000123"},
    }
    assert final["type"] == "final" and final["text"]


def test_especialista_sem_pedido_responde_direto():
    final = _content(_chat(_client(), [AGENT, {"role": "user", "content": "oi"}]))

    assert final["type"] == "final"


def test_modo_fora_do_ar_devolve_503_e_conta():
    client = _client(LLM_STUB_DOWN="1")

    assert _chat(client, [AGENT]).status_code == 503
    stats = client.get("/admin/stats").json()
    assert stats["counts"]["down_503"] == 1
    assert len(stats["rejected_at"]) == 1


def test_taxa_de_falha_total_devolve_500():
    assert _chat(_client(LLM_STUB_FAIL_RATE="1"), [AGENT]).status_code == 500


def test_modo_muda_em_tempo_de_execucao_e_registra_a_troca():
    client = _client()

    assert client.post("/admin/mode", json={"down": True}).json()["down"] is True
    assert _chat(client, [AGENT]).status_code == 503
    client.post("/admin/mode", json={"down": False})
    assert _chat(client, [AGENT]).status_code == 200

    changes = client.get("/admin/stats").json()["down_changes"]
    assert [down for _, down in changes] == [True, False]
    client.post("/admin/reset")
    assert client.get("/admin/stats").json()["counts"] == {}
