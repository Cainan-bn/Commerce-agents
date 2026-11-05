"""Ports de confirmação de ações irreversíveis (ADR 0008) e memória do cliente."""

from typing import Protocol


class ConfirmationTokenStore(Protocol):
    """Armazena tokens de uso único, com expiração, vinculados a conversa, ação e argumentos."""

    async def issue(
        self, conversation_id: str, action: str, arguments_digest: str, ttl_seconds: int
    ) -> str:
        """Emite um token novo."""
        ...

    async def consume(
        self, token: str, conversation_id: str, action: str, arguments_digest: str
    ) -> bool:
        """Consome o token. `False` se expirado, já usado ou vinculado a outra ação."""
        ...


class CustomerMemory(Protocol):
    """Memória de longo prazo de preferências do cliente."""

    async def get_preferences(self, customer_id: str) -> dict[str, str]: ...

    async def set_preference(self, customer_id: str, key: str, value: str) -> None: ...
