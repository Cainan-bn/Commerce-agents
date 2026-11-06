"""Fixtures da suíte de qualidade do RAG (modelo real; fora do `make test` padrão)."""

from tests.integration.persistence.conftest import (  # noqa: F401
    migration_sync_url,
    postgres_container,
)
from tests.integration.rag.conftest import rag_db  # noqa: F401
