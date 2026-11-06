"""Contrato do SqlCatalogSearch contra Postgres real."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_agents.domain.catalog.product import Product
from commerce_agents.infrastructure.persistence.models import ProductModel, VariantModel
from commerce_agents.infrastructure.persistence.repositories import SqlCatalogSearch
from tests.unit.domain.builders import make_product, make_variant

pytestmark = pytest.mark.integration


async def _insert_products(
    session_factory: async_sessionmaker[AsyncSession],
    products: tuple[Product, ...],
) -> None:
    async with session_factory() as session:
        for product in products:
            session.add(
                ProductModel(
                    product_id=product.product_id,
                    name=product.name,
                    brand=product.brand,
                    category=product.category,
                    price_cents=product.price_cents,
                    description=product.description,
                )
            )
            for variant in product.variants:
                session.add(
                    VariantModel(
                        sku=variant.sku,
                        product_id=product.product_id,
                        size=variant.size,
                        color=variant.color,
                        stock=variant.stock,
                    )
                )
        await session.commit()


def _default_products() -> tuple[Product, ...]:
    return (
        make_product(
            product_id="P0001",
            name="Tênis Urban Run",
            brand="Voltz",
            category="calcados",
            variants=(
                make_variant(sku="P0001-42-PRETO", stock=7),
                make_variant(sku="P0001-40-PRETO", size="40", stock=0),
            ),
        ),
        make_product(
            product_id="P0002",
            name="Camiseta Básica",
            brand="Alfa",
            category="camisetas",
            price_cents=5990,
            variants=(make_variant(sku="P0002-M-BRANCO", size="M", stock=3),),
        ),
    )


async def test_search_by_name_brand_and_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_products(session_factory, _default_products())
    search = SqlCatalogSearch(session_factory)

    by_name = await search.search("urban")
    by_brand = await search.search("voltz")
    by_category = await search.search("camisetas")

    assert [view.product_id for view in by_name] == ["P0001"]
    assert [view.product_id for view in by_brand] == ["P0001"]
    assert [view.product_id for view in by_category] == ["P0002"]


async def test_search_respects_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    extra = make_product(
        product_id="P0004",
        name="Tênis Urban Street",
        brand="Voltz",
        variants=(make_variant(sku="P0004-41-PRETO", size="41", stock=2),),
    )
    await _insert_products(session_factory, (*_default_products(), extra))
    search = SqlCatalogSearch(session_factory)

    all_matches = await search.search("urban", limit=10)
    limited = await search.search("urban", limit=1)

    assert len(all_matches) == 2
    assert len(limited) == 1


async def test_search_without_accent_finds_product_with_accent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_products(session_factory, _default_products())
    search = SqlCatalogSearch(session_factory)

    results = await search.search("tenis")

    assert [view.product_id for view in results] == ["P0001"]


async def test_search_ranks_more_relevant_product_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    shorter = make_product(
        product_id="P0001",
        name="Tênis Urban Run",
        variants=(make_variant(sku="P0001-42-PRETO", stock=7),),
    )
    longer = make_product(
        product_id="P0006",
        name="Tênis Urban Run Pro Max Ultra Edição Especial",
        brand="Voltz",
        variants=(make_variant(sku="P0006-42-PRETO", stock=1),),
    )
    await _insert_products(session_factory, (longer, shorter))
    search = SqlCatalogSearch(session_factory)

    results = await search.search("urban", limit=5)

    assert [view.product_id for view in results][:2] == ["P0001", "P0006"]


async def test_search_returns_empty_list_when_no_match(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_products(session_factory, _default_products())
    search = SqlCatalogSearch(session_factory)

    assert await search.search("produto-inexistente") == []


async def test_search_returns_product_view_with_variants_and_stock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_products(session_factory, _default_products())
    search = SqlCatalogSearch(session_factory)

    view = (await search.search("urban"))[0]

    assert view.product_id == "P0001"
    assert view.name == "Tênis Urban Run"
    assert view.brand == "Voltz"
    assert view.price_cents == 28990
    assert {variant.sku for variant in view.variants} == {
        "P0001-42-PRETO",
        "P0001-40-PRETO",
    }
    assert {variant.stock for variant in view.variants} == {7, 0}
