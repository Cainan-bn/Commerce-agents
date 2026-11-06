"""Geração determinística do catálogo de produtos da TH Multimarcas."""

from __future__ import annotations

import random

from data.generators.models import CATEGORIES, SIZES_BY_CATEGORY, Product, Variant

CATEGORY_COUNTS: dict[str, int] = {
    "calcados": 70,
    "camisetas": 70,
    "calcas": 60,
    "jaquetas": 55,
    "acessorios": 45,
}

BRANDS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "calcados": ("Voltz", "Duna", "Vega", "Prisma", "Raia", "Urbe"),
    "camisetas": ("Alfa", "Caju", "Fio", "Ginga", "Trama", "Soma"),
    "calcas": ("Beta", "Era", "Ibis", "Jambo", "Maré", "Zafra"),
    "jaquetas": ("Hera", "Lumen", "Nuvem", "Onda", "Quarta", "Kiwi"),
    "acessorios": ("Ginga", "Prisma", "Trama", "Lumen", "Soma", "Voltz"),
}

NAME_BASES: dict[str, tuple[str, ...]] = {
    "calcados": (
        "Tênis Urban Run",
        "Tênis Flex",
        "Tênis Trail",
        "Sapatênis Casual",
        "Chinelo Slide",
        "Sapatilha Conforto",
        "Bota Cano Curto",
        "Mocassim Couro",
        "Tênis Runner",
        "Tênis Slip-on",
        "Bota Chelsea",
        "Tênis Skate",
        "Rasteira Trançada",
        "Tênis Corrida",
        "Tênis Caminhada",
        "Sapato Social",
        "Bota Coturno",
        "Espadrille Linho",
        "Tênis Academia",
        "Sapatilha Bico Fino",
    ),
    "camisetas": (
        "Camiseta Básica",
        "Camiseta Estampada",
        "Regata Algodão",
        "Camiseta Oversized",
        "Polo Piquet",
        "Camiseta Gola V",
        "Camiseta Dry Fit",
        "Camiseta Tie Dye",
        "Blusa Manga Longa",
        "Camiseta Listrada",
        "Regata Esportiva",
        "Camiseta Premium",
        "Camiseta Cropped",
        "Camiseta Henley",
        "Camiseta Gola Careca",
        "Camiseta Neon",
        "Camiseta Jeans",
        "Camiseta Manga 3/4",
        "Camiseta Bordada",
        "Regata Canelada",
    ),
    "calcas": (
        "Calça Jeans Reta",
        "Calça Jeans Skinny",
        "Calça Sarja",
        "Calça Chino",
        "Calça Moletom",
        "Calça Jogger",
        "Calça Legging",
        "Calça Pantalona",
        "Calça Flare",
        "Calça Cargo",
        "Bermuda Jeans",
        "Shorts Sarja",
        "Calça Alfaiataria",
        "Calça Wide Leg",
        "Bermuda Moletom",
        "Calça Couro",
        "Calça Linho",
        "Calça Destroyed",
        "Shorts Esportivo",
        "Calça Cintura Alta",
    ),
    "jaquetas": (
        "Jaqueta Jeans",
        "Jaqueta Corta-Vento",
        "Jaqueta Couro",
        "Jaqueta Puffer",
        "Jaqueta Bomber",
        "Blazer Slim",
        "Jaqueta Nylon",
        "Cardigã Tricô",
        "Moletom Fechado",
        "Jaqueta Trench",
        "Jaqueta Militar",
        "Jaqueta Vinil",
        "Casaquinho Lã",
        "Jaqueta Parka",
        "Jaqueta Camurça",
        "Blazer Linho",
        "Jaqueta Acelerada",
        "Jaqueta Denim",
        "Colete Acolchoado",
        "Jaqueta Softshell",
    ),
    "acessorios": (
        "Boné Aba Curva",
        "Cinto Couro",
        "Meia Kit 3 Pares",
        "Óculos Solar",
        "Touca Tricô",
        "Cachecol Lã",
        "Bolsa Transversal",
        "Carteira Couro",
        "Mochila Urbana",
        "Relógio Minimalista",
        "Brinco Argola",
        "Colar Corrente",
        "Pulseira Aço",
        "Gorro Beanie",
        "Lenço Estampado",
        "Mochila Executiva",
        "Cinto Fivela",
        "Óculos Redondo",
        "Meia Esportiva Kit",
        "Bolsa Tote",
    ),
}

NAME_SUFFIXES: tuple[str, ...] = (
    "",
    "Pro",
    "Lite",
    "Classic",
    "Fit",
    "Air",
    "Max",
    "Prime",
    "Flex",
    "Urban",
    "Eco",
    "Trend",
    "Vibe",
    "Nitro",
    "Soft",
    "Active",
    "Premium",
    "Essencial",
)

COLORS: tuple[str, ...] = (
    "preto",
    "branco",
    "azul",
    "vermelho",
    "verde",
    "cinza",
    "marrom",
    "bege",
    "rosa",
    "vinho",
    "amarelo",
    "laranja",
)

PRICE_RANGE_BY_CATEGORY: dict[str, tuple[int, int]] = {
    "calcados": (99, 399),
    "camisetas": (39, 89),
    "calcas": (99, 199),
    "jaquetas": (199, 499),
    "acessorios": (19, 149),
}

DESCRIPTION_TEMPLATE: dict[str, str] = {
    "calcados": "Calçado {brand} com solado confortável e acabamento premium.",
    "camisetas": "Camiseta {brand} em algodão macio e caimento moderno.",
    "calcas": "Calça {brand} com modelagem atual e tecido resistente.",
    "jaquetas": "Jaqueta {brand} ideal para meia-estação, com forro leve.",
    "acessorios": "Acessório {brand} que completa o look do dia a dia.",
}


def _compose_name(bases: tuple[str, ...], index: int) -> str:
    base = bases[index % len(bases)]
    suffix = NAME_SUFFIXES[index // len(bases)]
    return f"{base} {suffix}" if suffix else base


def _build_variants(rng: random.Random, product_id: str, category: str) -> list[Variant]:
    colors = rng.sample(COLORS, k=rng.randint(1, 3))
    allowed = SIZES_BY_CATEGORY[category]
    if category == "acessorios":
        sizes = ["U"]
    elif category == "calcados":
        sizes = sorted(rng.sample(allowed, k=rng.randint(3, 5)), key=allowed.index)
    else:
        sizes = sorted(rng.sample(allowed, k=rng.randint(2, 4)), key=allowed.index)

    return [
        Variant(sku=f"{product_id}-{size}-{color.upper()}", size=size, color=color, stock=0)
        for size in sizes
        for color in colors
    ]


def _assign_stock(rng: random.Random, products: list[Product]) -> None:
    refs = [
        (product_index, variant_index)
        for product_index, product in enumerate(products)
        for variant_index in range(len(product.variants))
    ]
    rng.shuffle(refs)
    total = len(refs)
    zero_count = round(total * 0.15)
    low_count = round(total * 0.06)

    for product_index, variant_index in refs[:zero_count]:
        products[product_index].variants[variant_index].stock = 0
    for product_index, variant_index in refs[zero_count : zero_count + low_count]:
        products[product_index].variants[variant_index].stock = rng.choice((1, 2))
    for product_index, variant_index in refs[zero_count + low_count :]:
        products[product_index].variants[variant_index].stock = rng.randint(3, 50)


def generate_products(rng: random.Random) -> list[Product]:
    """Gera ~300 produtos-base com variações de tamanho/cor e estoque coerente."""
    products: list[Product] = []
    product_index = 0
    for category in CATEGORIES:
        bases = NAME_BASES[category]
        brands = BRANDS_BY_CATEGORY[category]
        lo, hi = PRICE_RANGE_BY_CATEGORY[category]
        for i in range(CATEGORY_COUNTS[category]):
            product_index += 1
            product_id = f"P{product_index:04d}"
            brand = rng.choice(brands)
            products.append(
                Product(
                    product_id=product_id,
                    name=_compose_name(bases, i),
                    brand=brand,
                    category=category,
                    price_cents=rng.randint(lo, hi) * 100 + 90,
                    description=DESCRIPTION_TEMPLATE[category].format(brand=brand),
                    variants=_build_variants(rng, product_id, category),
                )
            )
    _assign_stock(rng, products)
    return products
