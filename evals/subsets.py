"""Subconjuntos fixos de cenários."""

# 2 por categoria principal (pedidos, catalogo, politicas, pos_venda, ambiguo) + 2 de injection.
QUICK_SUBSET: tuple[str, ...] = (
    "PED-001",
    "IRR-001",
    "CAT-001",
    "CAT-002",
    "POL-001",
    "POL-003",
    "POS-001",
    "POS-006",
    "AMB-001",
    "AMB-002",
    "INJ-001",
    "INJ-002",
)
