"""Handlers internos do ToolExecutor (ferramentas `server="internal"`, ADR 0004/0013)."""

from typing import Any

from commerce_agents.application.dto.tools import (
    SearchPoliciesInput,
    SearchPoliciesOutput,
)
from commerce_agents.application.ports.repositories import PolicyRetriever


def make_search_policies_handler(retriever: PolicyRetriever) -> Any:
    """`search_policies` -> `PolicyRetriever.retrieve`, devolvendo trechos com fonte."""

    async def handler(agent: str, validated: Any) -> SearchPoliciesOutput:
        assert isinstance(validated, SearchPoliciesInput)
        chunks = await retriever.retrieve(validated.query, k=validated.top_k)
        return SearchPoliciesOutput(chunks=tuple(chunks))

    return handler
