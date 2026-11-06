"""Testes de integração do alvo `make seed`."""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FILES = ("products.jsonl", "customers.jsonl", "orders.jsonl")
COUNT_KEYS = ("produtos", "clientes", "pedidos", "variacoes")


def _run_make_seed(out_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SEED_OUT"] = str(out_dir)
    return subprocess.run(
        ["make", "seed"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _snapshot(out_dir: Path) -> dict[str, bytes]:
    return {name: (out_dir / name).read_bytes() for name in SEED_FILES}


def _counts(stdout: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in COUNT_KEYS:
            parsed[key] = int(value)
    return parsed


@pytest.mark.integration
def test_make_seed_is_idempotent(tmp_path: Path) -> None:
    out_dir = tmp_path / "seed"

    first = _run_make_seed(out_dir)
    assert first.returncode == 0, first.stderr
    for name in SEED_FILES:
        assert (out_dir / name).is_file()

    counts = _counts(first.stdout)
    assert set(counts) == set(COUNT_KEYS)
    assert all(total > 0 for total in counts.values())

    snapshot = _snapshot(out_dir)

    second = _run_make_seed(out_dir)
    assert second.returncode == 0, second.stderr
    assert _counts(second.stdout) == counts
    assert _snapshot(out_dir) == snapshot


@pytest.mark.integration
def test_seed_validation_fails_on_empty_dir(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = subprocess.run(
        ["uv", "run", "python", "scripts/validate_seed.py", str(empty_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode != 0
    assert "contagem" in result.stderr.lower()
