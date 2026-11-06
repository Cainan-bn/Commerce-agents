"""Servidores MCP: cada um expõe exatamente suas ferramentas e despacha pelo executor."""

import httpx
import pytest

from commerce_agents.application.dto.tools import INPUT_MODELS, TOOL_SPECS
from commerce_agents.infrastructure.mcp import __main__ as entrypoint
from commerce_agents.infrastructure.mcp.memory import (
    InMemoryIdempotencyRegistry,
    InMemoryTokenStore,
)
from commerce_agents.infrastructure.mcp.servers import ServerName, build_server
from tests.fakes.tools import SAMPLE_ARGUMENTS

pytestmark = pytest.mark.unit

SERVER_TOOLS: dict[ServerName, set[str]] = {
    "orders": {"get_order_status", "list_customer_orders", "cancel_order"},
    "catalog": {"search_products", "check_availability"},
    "shipping": {"quote_shipping"},
    "returns": {"check_return_eligibility", "open_return"},
}


@pytest.mark.parametrize("name", list(SERVER_TOOLS))
async def test_servidor_expoe_exatamente_suas_ferramentas(make_unit_executor, name: ServerName):
    server = build_server(name, make_unit_executor(), lambda: "Pedidos")

    tools = await server.list_tools()

    assert {t.name for t in tools} == SERVER_TOOLS[name]
    assert {n for n, s in TOOL_SPECS.items() if s.server == name} == SERVER_TOOLS[name]
    for tool in tools:
        assert tool.inputSchema == INPUT_MODELS[tool.name].model_json_schema()
        assert tool.description


async def test_chamada_passa_pelo_executor(make_unit_executor, transport):
    server = build_server("orders", make_unit_executor(), lambda: "Pedidos")

    result = await server.call_tool("get_order_status", SAMPLE_ARGUMENTS["get_order_status"])

    assert result["ok"] is False  # loja de teste responde 500: prova que o executor foi usado
    assert result["code"] == "upstream_error"
    assert len(transport.requests) == 1


async def test_allowlist_do_agente_vale_no_servidor(make_unit_executor, transport):
    server = build_server("orders", make_unit_executor(), lambda: "CatalogoVendas")

    result = await server.call_tool("get_order_status", SAMPLE_ARGUMENTS["get_order_status"])

    assert result["code"] == "not_allowed"
    assert transport.requests == []


async def test_ferramenta_de_outro_servidor_e_desconhecida(make_unit_executor):
    server = build_server("orders", make_unit_executor(), lambda: "Pedidos")

    with pytest.raises(ValueError, match="desconhecida"):
        await server.call_tool("search_products", {"query": "x"})


async def test_adaptadores_em_memoria_seguem_o_contrato_dos_ports():
    now = [0.0]
    tokens = InMemoryTokenStore(clock=lambda: now[0])
    token = await tokens.issue("c", "cancel_order", "d", 10)
    assert await tokens.consume(token, "c", "outra", "d") is False
    assert await tokens.consume(token, "c", "cancel_order", "d") is True
    assert await tokens.consume(token, "c", "cancel_order", "d") is False
    expired = await tokens.issue("c", "cancel_order", "d", 10)
    now[0] = 11.0
    assert await tokens.consume(expired, "c", "cancel_order", "d") is False
    assert await tokens.consume("inexistente", "c", "cancel_order", "d") is False

    registry = InMemoryIdempotencyRegistry()
    assert await registry.get("k") is None
    await registry.put("k", "f", "{}")
    assert await registry.get("k") == ("f", "{}")


def test_main_sobe_servidor_stdio_com_store_base_url(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class _Fake:
        def run(self, transport: str) -> None:
            captured["transport"] = transport

    def _build(name: str, executor: object, resolver: object) -> _Fake:
        captured["name"] = name
        captured["agent"] = resolver()  # type: ignore[operator]
        captured["client"] = executor._client  # type: ignore[attr-defined]
        return _Fake()

    monkeypatch.setenv("STORE_BASE_URL", "http://loja:9")
    monkeypatch.setattr(entrypoint, "build_server", _build)

    entrypoint.main(["catalog", "--agent", "CatalogoVendas"])

    assert captured["transport"] == "stdio"
    assert (captured["name"], captured["agent"]) == ("catalog", "CatalogoVendas")
    assert isinstance(captured["client"], httpx.AsyncClient)
    assert str(captured["client"].base_url).startswith("http://loja:9")  # type: ignore[attr-defined]


def test_main_usa_url_padrao_sem_variavel(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}

    class _Fake:
        def run(self, transport: str) -> None: ...

    def _build(name: str, executor: object, resolver: object) -> _Fake:
        seen["url"] = str(executor._client.base_url)  # type: ignore[attr-defined]
        return _Fake()

    monkeypatch.delenv("STORE_BASE_URL", raising=False)
    monkeypatch.setattr(entrypoint, "build_server", _build)

    entrypoint.main(["orders", "--agent", "Pedidos"])

    assert seen["url"].startswith(entrypoint.DEFAULT_STORE_BASE_URL)  # type: ignore[attr-defined]


def test_build_stores_sem_banco_usa_memoria_com_aviso(caplog: pytest.LogCaptureFixture):
    with caplog.at_level("WARNING"):
        tokens, idempotency = entrypoint.build_stores({"STORE_BASE_URL": "http://x"})

    assert isinstance(tokens, InMemoryTokenStore)
    assert isinstance(idempotency, InMemoryIdempotencyRegistry)
    assert "em memória" in caplog.text


@pytest.mark.parametrize(
    "environ",
    [
        {"DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/commerce"},
        {"POSTGRES_HOST": "db"},
    ],
)
def test_build_stores_com_banco_usa_adaptadores_sql(environ: dict[str, str]):
    from commerce_agents.infrastructure.persistence.idempotency import SqlIdempotencyRegistry
    from commerce_agents.infrastructure.persistence.token_store import SqlConfirmationTokenStore

    tokens, idempotency = entrypoint.build_stores(environ)

    assert isinstance(tokens, SqlConfirmationTokenStore)
    assert isinstance(idempotency, SqlIdempotencyRegistry)
