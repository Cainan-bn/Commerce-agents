"""Engine e fábrica de sessões assíncronas (SQLAlchemy 2)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    """Cria o engine assíncrono a partir da URL (driver asyncpg)."""
    return create_async_engine(url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Cria a fábrica de sessões assíncronas, sem expirar objetos no commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
