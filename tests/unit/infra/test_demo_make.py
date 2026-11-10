"""Alvos de demonstração do Makefile (ADR 0020), conferidos por `make -n` (sem rede).

- demo-record: infra do compose de pé, API e worker NO HOST com `LLM_PROVIDER=opencode-cli`,
  `LLM_RECORD_TO=data/demo/cassette.jsonl` e `DEMO_MODE=true`, roda o driver e derruba API e worker;
- demo-verify: stack de produção com `LLM_PROVIDER=recorded` e
  `LLM_CASSETTE=/app/data/demo/cassette.jsonl`, driver com `--expect-no-miss`;
- demo: o mesmo `up` do demo-verify (volumes limpos, build local, LLM gravado, segredos locais),
  sem o driver e sem derrubar; espera `/health` e imprime as URLs (demo, painel com o
  `PANEL_TOKEN`, Grafana com usuário e senha, Jaeger); demo-down: `down -v`.
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


def test_demo_sobe_a_demonstracao_sem_o_driver_e_sem_derrubar():
    receita = _dry_run("demo")

    assert "docker-compose.prod.yml" in receita
    assert "down -v" in receita  # começa de volumes limpos
    assert "up -d --build" in receita
    assert "DEMO_MODE=true" in receita
    assert "LLM_PROVIDER=recorded" in receita
    assert "/app/data/demo/cassette.jsonl" in receita
    assert "/health" in receita
    assert "scripts/demo_drive.py" not in receita
    assert "trap" not in receita  # não derruba ao terminar


def test_demo_imprime_as_urls_com_as_credenciais_usadas():
    receita = _dry_run("demo")

    assert "/demo" in receita
    assert "/panel" in receita
    assert "PANEL_TOKEN" in receita
    assert "3001" in receita
    assert "GRAFANA_ADMIN_PASSWORD" in receita
    assert "16686" in receita


def test_demo_down_derruba_e_apaga_os_volumes():
    receita = _dry_run("demo-down")

    assert "docker-compose.prod.yml" in receita
    assert "down -v" in receita


def test_demo_e_demo_down_aparecem_no_help():
    ajuda = subprocess.run(  # noqa: S603
        ["make", "help"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    assert "demo-down" in ajuda
    assert any(line.split()[:1] == ["demo"] for line in _strip_ansi(ajuda).splitlines())


def _strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)
