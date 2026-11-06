"""CLI do gerador de seed: python -m data.generators --seed 42 --out data/seed."""

from __future__ import annotations

import argparse
from pathlib import Path

from data.generators.generate import DEFAULT_OUT, DEFAULT_SEED, generate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="data.generators",
        description="Gera o dataset determinístico e fictício da TH Multimarcas.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="semente do RNG")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="diretório de saída dos arquivos JSONL"
    )
    args = parser.parse_args(argv)

    counts = generate(args.seed, args.out)
    for name, total in counts.items():
        print(f"{name}={total}")


if __name__ == "__main__":
    main()
