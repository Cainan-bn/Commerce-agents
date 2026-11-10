"""Alvos `make demo-record` e `make demo-verify` (ADR 0020, TASK-10-03a), conferidos por `make -n`.

- demo-record: infra do compose de pé, API e worker NO HOST com `LLM_PROVIDER=opencode-cli`,
  `LLM_RECORD_TO=data/demo/cassette.jsonl` e `DEMO_MODE=true`, roda o driver e derruba API e worker;
- demo-verify: stack de produção com `LLM_PROVIDER=recorded` e
  `LLM_CASSETTE=/app/data/demo/cassette.jsonl`, driver com `--expect-no-miss`.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]


def _dry_run(target: str) -> str:
    result = subprocess.run(  # noqa: S603 - make do sistema, alvo fixo, sem executar receitas
        ["make", "-n", target],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_demo_record_grava_pelo_caminho_real_no_host():
    receita = _dry_run("demo-record")

    assert "LLM_PROVIDER=opencode-cli" in receita
    assert "LLM_RECORD_TO=data/demo/cassette.jsonl" in receita
    assert "DEMO_MODE=true" in receita
    assert "scripts/demo_drive.py" in receita
    assert "commerce_agents.interfaces.main:app" in receita
    assert "commerce_agents.interfaces.worker" in receita


def test_demo_verify_usa_a_stack_de_producao_com_o_cassete():
    receita = _dry_run("demo-verify")

    assert "docker-compose.prod.yml" in receita
    assert "LLM_PROVIDER=recorded" in receita
    assert "/app/data/demo/cassette.jsonl" in receita
    assert "scripts/demo_drive.py" in receita
    assert "--expect-no-miss" in receita


def test_alvos_aparecem_no_help():
    ajuda = subprocess.run(  # noqa: S603
        ["make", "help"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    assert "demo-record" in ajuda
    assert "demo-verify" in ajuda
