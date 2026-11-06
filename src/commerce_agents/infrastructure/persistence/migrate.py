"""Migração programática via Alembic, sem depender de alembic.ini no CWD."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_DEFAULT_DB = "commerce"
_DEFAULT_USER = "commerce"
_DEFAULT_PASSWORD = "dev-only-change-me"  # pragma: allowlist secret
_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = "5432"


def _config(sync_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", sync_url)
    return config


def sync_url_from_async(async_url: str) -> str:
    """Converte a URL assíncrona (asyncpg) na URL síncrona (psycopg)."""
    return async_url.replace("+asyncpg", "+psycopg")


def sync_url_from_env() -> str:
    """Deriva a URL síncrona a partir de ``DATABASE_URL`` ou das variáveis ``POSTGRES_*``."""
    url = os.environ.get("DATABASE_URL")
    if url and "@" in url and ":@" not in url:
        return sync_url_from_async(url)
    user = os.environ.get("POSTGRES_USER", _DEFAULT_USER)
    password = os.environ.get("POSTGRES_PASSWORD", _DEFAULT_PASSWORD)
    host = os.environ.get("POSTGRES_HOST", _DEFAULT_HOST)
    port = os.environ.get("POSTGRES_PORT", _DEFAULT_PORT)
    db = os.environ.get("POSTGRES_DB", _DEFAULT_DB)
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def upgrade_to_head(sync_url: str) -> None:
    """Aplica todas as migrações pendentes até ``head``."""
    command.upgrade(_config(sync_url), "head")


def downgrade_to_base(sync_url: str) -> None:
    """Reverte todas as migrações até a base (útil em testes)."""
    command.downgrade(_config(sync_url), "base")
