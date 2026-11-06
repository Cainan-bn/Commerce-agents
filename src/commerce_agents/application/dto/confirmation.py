"""DTOs do fluxo de confirmação de ações irreversíveis (ADR 0008, 0011)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel
from commerce_agents.application.dto.tools import ToolError


class PendingAction(StrictModel):
    """Proposta aguardando a resposta do cliente. Guardada no estado da conversa (checkpoint)."""

    conversation_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(description="Somente os `action_fields` da ferramenta")
    confirmation_token: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8)
    summary: str = Field(description="Texto pt-BR mostrado ao cliente, pedindo confirmação")
    expires_at: datetime


class Reply(StrEnum):
    """Classificação determinística (código, não LLM) da resposta do cliente."""

    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"
    UNCLEAR = "unclear"


class ConfirmationStatus(StrEnum):
    EXECUTED = "executed"  # ferramenta executada com sucesso
    FAILED = "failed"  # cliente confirmou, mas a ferramenta devolveu ToolError
    DECLINED = "declined"  # cliente recusou; proposta descartada
    UNCLEAR = "unclear"  # resposta ambígua; perguntar de novo, proposta mantida
    EXPIRED = "expired"  # proposta expirada; nada executado


class ConfirmationOutcome(StrictModel):
    status: ConfirmationStatus
    result: StrictModel | None = Field(default=None, description="Output da ferramenta (EXECUTED)")
    error: ToolError | None = Field(default=None, description="Erro da ferramenta (FAILED)")
