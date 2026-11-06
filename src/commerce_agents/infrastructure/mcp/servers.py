"""Servidores MCP por domínio (orders, catalog, shipping, returns), ADR 0004.

Os schemas anunciados vêm de `INPUT_MODELS` e toda chamada passa pelo `ToolExecutor`, que
aplica allowlist, token, idempotência e auditoria. O servidor não contém regra de negócio.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool

from commerce_agents.application.dto.tools import INPUT_MODELS, TOOL_SPECS
from commerce_agents.infrastructure.mcp.executor import ToolExecutor

ServerName = Literal["orders", "catalog", "shipping", "returns"]
AgentResolver = Callable[[], str]

_DESCRIPTIONS: dict[str, str] = {
    "get_order_status": "Consulta o status, o rastreio e as datas de um pedido.",
    "list_customer_orders": "Lista os pedidos mais recentes de um cliente.",
    "cancel_order": "Cancela um pedido. Irreversível: exige token de confirmação do cliente.",
    "search_products": "Busca produtos do catálogo por nome, marca ou categoria.",
    "check_availability": "Verifica estoque de um produto, opcionalmente por tamanho e cor.",
    "quote_shipping": "Cota frete e prazo de entrega para um CEP e uma lista de itens.",
    "check_return_eligibility": "Verifica se um item de um pedido pode ser devolvido.",
    "open_return": "Abre devolução de um item. Irreversível: exige token de confirmação.",
}


class _ContractServer(FastMCP):
    """FastMCP cujo catálogo e despacho vêm do contrato de `application/dto/tools.py`."""

    def __init__(
        self, name: ServerName, executor: ToolExecutor, agent_resolver: AgentResolver
    ) -> None:
        super().__init__(name=f"commerce-{name}")
        self._tool_names = sorted(n for n, spec in TOOL_SPECS.items() if spec.server == name)
        self._executor = executor
        self._agent_resolver = agent_resolver

    async def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(
                name=tool_name,
                description=_DESCRIPTIONS[tool_name],
                inputSchema=INPUT_MODELS[tool_name].model_json_schema(),
            )
            for tool_name in self._tool_names
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tool_names:
            raise ValueError(f"Ferramenta desconhecida: {name}")
        result = await self._executor.invoke(self._agent_resolver(), name, arguments)
        return result.model_dump(mode="json")


def build_server(
    name: ServerName, executor: ToolExecutor, agent_resolver: AgentResolver
) -> FastMCP:
    """Cria o servidor MCP de um domínio. `agent_resolver` informa o agente chamador."""
    return _ContractServer(name, executor, agent_resolver)
