"""checks numericos e busca sem acento

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_SEARCH_VECTOR_SQL = "to_tsvector('portuguese'::regconfig, name || ' ' || brand || ' ' || category)"
_SEARCH_VECTOR_UNACCENT_SQL = (
    "to_tsvector('portuguese'::regconfig, "
    "public.immutable_unaccent(name || ' ' || brand || ' ' || category))"
)

_CHECKS = (
    ("ck_orders_total_cents_nonnegative", "orders", "total_cents >= 0"),
    ("ck_order_items_unit_price_nonnegative", "order_items", "unit_price_cents >= 0"),
    ("ck_order_items_qty_positive", "order_items", "qty >= 1"),
    ("ck_product_variants_stock_nonnegative", "product_variants", "stock >= 0"),
    ("ck_products_price_nonnegative", "products", "price_cents >= 0"),
)


def _recreate_search_vector(expression: str) -> None:
    op.drop_index("ix_products_search_vector", table_name="products")
    op.drop_column("products", "search_vector")
    op.add_column(
        "products",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(expression, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_products_search_vector",
        "products",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def upgrade() -> None:
    for name, table, condition in _CHECKS:
        op.create_check_constraint(name, table, condition)

    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        "CREATE OR REPLACE FUNCTION public.immutable_unaccent(text) "
        "RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT "
        "AS $$ SELECT public.unaccent('public.unaccent', $1) $$"
    )

    _recreate_search_vector(_SEARCH_VECTOR_UNACCENT_SQL)


def downgrade() -> None:
    _recreate_search_vector(_SEARCH_VECTOR_SQL)

    op.execute("DROP FUNCTION IF EXISTS public.immutable_unaccent(text)")
    # A extensão unaccent pode permanecer instalada.

    for name, table, _condition in reversed(_CHECKS):
        op.drop_constraint(name, table, type_="check")
