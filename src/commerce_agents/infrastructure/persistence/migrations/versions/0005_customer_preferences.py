"""preferencias de longo prazo do cliente (memoria do orquestrador)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_preferences",
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("char_length(key) > 0", name="ck_customer_preferences_key_nonempty"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("customer_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("customer_preferences")
