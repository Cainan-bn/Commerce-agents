"""trechos de politicas para busca hibrida (pgvector + tsvector)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_SEARCH_VECTOR_SQL = (
    "to_tsvector('portuguese'::regconfig, "
    "public.immutable_unaccent(title || ' ' || section || ' ' || text))"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.create_table(
        "policy_chunks",
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("corpus_version", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(_SEARCH_VECTOR_SQL, persisted=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        "ix_policy_chunks_search_vector", "policy_chunks", ["search_vector"], postgresql_using="gin"
    )
    op.create_index(
        "ix_policy_chunks_embedding",
        "policy_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_policy_chunks_embedding", table_name="policy_chunks")
    op.drop_index("ix_policy_chunks_search_vector", table_name="policy_chunks")
    op.drop_table("policy_chunks")
