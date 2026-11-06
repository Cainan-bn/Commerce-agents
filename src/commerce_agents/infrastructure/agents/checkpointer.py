"""Checkpointer Postgres do grafo (langgraph-checkpoint-postgres), aberto sob demanda.

A fábrica é síncrona para poder ser chamada na composição do app: o pool abre e o schema do
checkpointer é criado (`setup()`, idempotente) no primeiro uso, dentro do event loop corrente.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_IN_SETUP: ContextVar[bool] = ContextVar("checkpointer_in_setup", default=False)
_POOL_SIZE = 5


class LazyPostgresSaver(AsyncPostgresSaver):
    """`AsyncPostgresSaver` que abre o pool e roda `setup()` uma única vez, no primeiro uso."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        super().__init__(pool)
        self._pool = pool
        self._ready = False
        self._init_lock = asyncio.Lock()

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            await self._pool.open()
            token = _IN_SETUP.set(True)
            try:
                await self.setup()
            finally:
                _IN_SETUP.reset(token)
            self._ready = True

    @asynccontextmanager
    async def _cursor(self, *, pipeline: bool = False) -> AsyncIterator[Any]:
        if not _IN_SETUP.get():
            await self._ensure_ready()
        async with super()._cursor(pipeline=pipeline) as cursor:
            yield cursor

    async def aclose(self) -> None:
        await self._pool.close()


def create_postgres_checkpointer(url: str) -> LazyPostgresSaver:
    """Cria o checkpointer para `url` (formato libpq: `postgresql://...`). Chamar com loop ativo."""
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=_POOL_SIZE,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    return LazyPostgresSaver(pool)
