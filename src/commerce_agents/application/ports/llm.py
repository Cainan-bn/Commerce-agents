"""Ports de LLM e de roteamento de intenção."""

from typing import Protocol

from commerce_agents.application.dto.views import IntentDecision, LLMMessage, LLMResult


class LLMProvider(Protocol):
    """Provider de LLM. Implementações tratam retry, circuit breaker e fallback."""

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        """Gera uma resposta. Levanta erro tipado quando o provider está indisponível."""
        ...


class IntentRouter(Protocol):
    """Classifica a intenção da mensagem. Baseline: modelo leve; evolução: SLM fine-tuned."""

    async def route(self, text: str) -> IntentDecision:
        """Retorna a intenção e a confiança, validadas por schema."""
        ...


class LLMUnavailableError(Exception):
    """Provider indisponível (429, 5xx, timeout ou rede) após esgotar as tentativas."""


class LLMBadRequestError(Exception):
    """Requisição recusada pelo provider (4xx exceto 429); não adianta repetir."""
