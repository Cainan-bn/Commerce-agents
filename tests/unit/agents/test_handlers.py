"""Handler interno `search_policies` -> PolicyRetriever."""

import pytest

from commerce_agents.application.dto.tools import SearchPoliciesInput, SearchPoliciesOutput
from commerce_agents.infrastructure.agents.handlers import make_search_policies_handler
from tests.fakes.agents import policy_chunk

pytestmark = pytest.mark.unit


class _Retriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, query: str, k: int = 4):  # type: ignore[no-untyped-def]
        self.calls.append((query, k))
        return [policy_chunk("troca#0")]


async def test_search_policies_chama_o_retriever_com_top_k():
    retriever = _Retriever()
    handler = make_search_policies_handler(retriever)

    result = await handler("Politicas", SearchPoliciesInput(query="prazo de troca", top_k=3))

    assert isinstance(result, SearchPoliciesOutput)
    assert [chunk.chunk_id for chunk in result.chunks] == ["troca#0"]
    assert retriever.calls == [("prazo de troca", 3)]
