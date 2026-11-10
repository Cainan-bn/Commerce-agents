"""Guarda: nenhum teste sob tests/unit fica fora de `-m unit` (o filtro do gate e do CI)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

UNIT_DIR = Path(__file__).parent
NO_TESTS_COLLECTED = 5


def test_nenhum_teste_de_tests_unit_fica_fora_do_marcador_unit():
    result = subprocess.run(  # noqa: S603 - pytest do próprio ambiente, argumentos fixos
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "not unit",
            "-p",
            "no:cacheprovider",
            "--no-cov",
            str(UNIT_DIR),
        ],
        capture_output=True,
        text=True,
        cwd=UNIT_DIR.parents[1],
        check=False,
    )

    fora = [line for line in result.stdout.splitlines() if "::" in line]
    assert fora == [], f"testes fora de -m unit: {fora[:10]}"
    assert result.returncode == NO_TESTS_COLLECTED, result.stdout[-500:] + result.stderr[-500:]
