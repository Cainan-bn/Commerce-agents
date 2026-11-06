"""LLM roteirizado para testes: devolve respostas na ordem e registra as mensagens recebidas."""

from __future__ import annotations

from collections.abc import Sequence

from commerce_agents.application.dto.views import LLMMessage, LLMResult


class ScriptedLLMExhausted(RuntimeError):
    """O roteiro acabou e o teste fez uma chamada a mais ao LLM."""


class ScriptedLLM:
    """Implementa `LLMProvider`. Cada item do roteiro é o texto devolvido ou uma exceção levantada.

    `calls` guarda a lista de mensagens de cada chamada, para inspecionar o prompt montado.
    """

    def __init__(
        self, responses: Sequence[str | Exception], *, model: str = "scripted-test"
    ) -> None:
        self._responses = list(responses)
        self._model = model
        self.calls: list[list[LLMMessage]] = []

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> LLMResult:
        self.calls.append(list(messages))
        if not self._responses:
            raise ScriptedLLMExhausted("roteiro esgotado: chamada inesperada ao LLM")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(content=item, model=self._model, input_tokens=10, output_tokens=5)

    @property
    def remaining(self) -> int:
        return len(self._responses)

    def last_user_content(self) -> str:
        """Conteúdo da última mensagem enviada na última chamada."""
        return self.calls[-1][-1].content
