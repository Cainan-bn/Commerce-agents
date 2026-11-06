"""Relatório de avaliação (evals.md): JSON e Markdown em tmp_path, comparação antes × depois."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _report_module():  # type: ignore[no-untyped-def]
    from evals import report

    return report


def _sample_report() -> dict:  # type: ignore[type-arg]
    return {
        "label": "baseline",
        "commit": "abc1234",
        "corpus_version": "v1",
        "models": {"agent": "opencode-go/claude-haiku-5-5", "judge": "opencode-go/gpt-6-luna"},
        "temperature": 0.0,
        "cost_usd": 0.42,
        "rates": {"tool_selection": 0.9, "intent_agent": 0.8},
        "by_category": {"pedidos": {"tool_selection": 1.0}, "politicas": {"tool_selection": 0.5}},
        "scenarios": [
            {
                "id": "PED-001",
                "category": "pedidos",
                "scenario_pass": True,
                "metrics": {"tool_selection": True},
            },
            {
                "id": "POL-001",
                "category": "politicas",
                "scenario_pass": False,
                "metrics": {"tool_selection": False},
                "failure_excerpt": "resposta sem a palavra 7 dias",
            },
        ],
        "infra_errors": 0,
    }


def test_grava_json_e_markdown(tmp_path: Path):
    report = _report_module()

    written = report.write_report(_sample_report(), tmp_path, timestamp="20261106-120000")

    json_path = next(p for p in written if p.suffix == ".json")
    md_path = next(p for p in written if p.suffix == ".md")
    assert json.loads(json_path.read_text(encoding="utf-8"))["label"] == "baseline"
    assert md_path.read_text(encoding="utf-8")


def test_markdown_traz_tabela_falhas_custo_hash_e_modelos(tmp_path: Path):
    report = _report_module()

    written = report.write_report(_sample_report(), tmp_path, timestamp="20261106-120000")
    md = next(p for p in written if p.suffix == ".md").read_text(encoding="utf-8")

    assert "tool_selection" in md
    assert "pedidos" in md and "politicas" in md
    assert "POL-001" in md
    assert "resposta sem a palavra 7 dias" in md
    assert "0.42" in md
    assert "abc1234" in md
    assert "opencode-go/claude-haiku-5-5" in md
    assert "opencode-go/gpt-6-luna" in md


def test_compare_lista_melhorias_e_pioras_por_cenario():
    report = _report_module()
    before = _sample_report()
    after = _sample_report()
    after["scenarios"][0]["scenario_pass"] = False
    after["scenarios"][1]["scenario_pass"] = True

    diff = report.compare(before, after)

    assert diff["improved"] == ["POL-001"]
    assert diff["worsened"] == ["PED-001"]
