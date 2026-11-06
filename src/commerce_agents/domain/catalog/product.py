"""Entidades de catálogo: produto e variação."""

from dataclasses import dataclass

from commerce_agents.domain.shared.errors import InvariantViolation


@dataclass(frozen=True)
class Variant:
    """Variação de produto (tamanho/cor) com a quantidade em estoque."""

    sku: str
    size: str
    color: str
    stock: int

    @property
    def is_in_stock(self) -> bool:
        """Indica se há ao menos uma unidade em estoque."""
        return self.stock > 0

    def can_fulfill(self, qty: int) -> bool:
        """Indica se o estoque atende a quantidade pedida."""
        return 1 <= qty <= self.stock


@dataclass(frozen=True)
class Product:
    """Produto do catálogo com suas variações."""

    product_id: str
    name: str
    brand: str
    category: str
    price_cents: int
    description: str
    variants: tuple[Variant, ...]

    def variant(self, sku: str) -> Variant:
        """Retorna a variação pelo SKU ou lança InvariantViolation."""
        for variant in self.variants:
            if variant.sku == sku:
                return variant
        raise InvariantViolation(f"sku inexistente: {sku}")
