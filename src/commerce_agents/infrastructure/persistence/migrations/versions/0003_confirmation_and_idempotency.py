"""tokens de confirmacao e registros de idempotencia

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "confirmation_tokens",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("arguments_digest", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(token_hash) = 64", name="ck_confirmation_tokens_hash_len"),
        sa.CheckConstraint(
            "char_length(arguments_digest) = 64", name="ck_confirmation_tokens_digest_len"
        ),
        sa.CheckConstraint(
            "char_length(action) > 0", name="ck_confirmation_tokens_action_nonempty"
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("char_length(key) > 0", name="ck_idempotency_records_key_nonempty"),
        sa.CheckConstraint(
            "char_length(fingerprint) > 0", name="ck_idempotency_records_fingerprint_nonempty"
        ),
        sa.CheckConstraint(
            "char_length(result_json) > 0", name="ck_idempotency_records_result_nonempty"
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("confirmation_tokens")
