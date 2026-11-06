"""Valida a carga do seed pelo mock_store e imprime as contagens."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COUNT_KEYS = ("produtos", "clientes", "pedidos", "variacoes")


def counts_for(data_dir: Path) -> dict[str, int]:
    from mock_store.store import MockStore

    store = MockStore(data_dir)
    return {
        "produtos": len(store.products),
        "clientes": len(store.customers),
        "pedidos": len(store.orders),
        "variacoes": sum(len(product.variants) for product in store.products.values()),
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    data_dir = Path(args[0]) if args else Path("data/seed")

    try:
        counts = counts_for(data_dir)
    except Exception as error:
        print(f"erro ao carregar seed em {data_dir}: {error}", file=sys.stderr)
        return 1

    for key in COUNT_KEYS:
        print(f"{key}={counts[key]}")

    empty = [key for key in COUNT_KEYS if counts[key] == 0]
    if empty:
        print(f"seed invalido: contagem zero em {', '.join(empty)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
