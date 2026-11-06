"""Helpers dos testes de integração dos adaptadores de confirmação e idempotência."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from commerce_agents.infrastructure.persistence.database import create_engine


def async_url_for(sync_url: str) -> str:
    return sync_url.replace("+psycopg", "+asyncpg")


def new_engine_for(engine: AsyncEngine) -> AsyncEngine:
    """Segundo engine para o mesmo banco: simula outro processo."""
    return create_engine(engine.url.render_as_string(hide_password=False))
