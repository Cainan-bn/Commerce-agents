"""ledger de entregas aos canais

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10

"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivered_messages",
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("ix_delivered_messages_delivered_at", "delivered_messages", ["delivered_at"])


def downgrade() -> None:
    op.drop_index("ix_delivered_messages_delivered_at", table_name="delivered_messages")
    op.drop_table("delivered_messages")
