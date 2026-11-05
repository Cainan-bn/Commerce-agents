"""Port de relógio, para tornar regras de prazo determinísticas em testes."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Fornece o instante atual (timezone-aware, UTC)."""

    def now(self) -> datetime: ...
