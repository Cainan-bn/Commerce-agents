"""traceparent no outbox

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10

"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("traceparent", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("outbox", "traceparent")
