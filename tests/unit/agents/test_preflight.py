"""preflight_irreversible: respostas inesperadas da loja e ferramentas sem pré-checagem."""

from typing import Any

import pytest

from commerce_agents.application.agents.preflight import preflight_irreversible
from commerce_agents.application.dto.tools import SearchPoliciesOutput, ToolErrorCode

pytestmark = pytest.mark.unit


class _Inner:
    async def invoke(self, agent: str, tool_name: str, arguments: Any, **kwargs: Any) -> Any:
        return SearchPoliciesOutput(chunks=())


@pytest.mark.parametrize("tool", ["cancel_order", "open_return"])
async def test_resposta_inesperada_vira_upstream_error(tool: str):
    result = await preflight_irreversible(
        _Inner(),
        "Pedidos",
        tool,
        {"order_id": "O000001", "sku": "P0001-M-AZUL"},
        conversation_id="c",
    )

    assert result is not None
    assert result.code is ToolErrorCode.UPSTREAM_ERROR


async def test_ferramenta_sem_regra_passa():
    assert (
        await preflight_irreversible(_Inner(), "Pedidos", "outra", {}, conversation_id="c") is None
    )
