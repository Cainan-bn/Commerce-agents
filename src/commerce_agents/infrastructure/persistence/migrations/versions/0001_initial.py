"""schema inicial

Revision ID: 0001
Revises:
Create Date: 2026-11-06

"""

from alembic import op
from sqlalchemy import Table

from commerce_agents.infrastructure.persistence.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tabelas criadas por revisões posteriores: o metadata atual as inclui, mas esta revisão não.
_LATER_TABLES = frozenset({"confirmation_tokens", "idempotency_records", "policy_chunks"})


def _initial_tables() -> list[Table]:
    return [table for table in Base.metadata.sorted_tables if table.name not in _LATER_TABLES]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_initial_tables())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_initial_tables())
