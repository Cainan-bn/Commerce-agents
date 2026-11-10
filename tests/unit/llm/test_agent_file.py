"""Agente `plain` do opencode (ADR 0015): sem ferramentas, temperatura 0, permissões negadas."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

AGENT_FILE = (
    Path(__file__).resolve().parents[3] / "evals" / "opencode" / ".opencode" / "agent" / "plain.md"
)
DENIED_TOOLS = ("bash", "write", "edit", "read", "webfetch")
DENIED_PERMISSIONS = ("edit", "bash", "webfetch")


def _front_matter() -> dict:
    text = AGENT_FILE.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "o agente precisa de front matter YAML"
    _, header, body = text.split("---\n", 2)
    assert body.strip(), "o agente precisa de instrução no corpo"
    return yaml.safe_load(header)


def test_arquivo_do_agente_existe():
    assert AGENT_FILE.is_file()


def test_temperatura_zero():
    assert _front_matter()["temperature"] == 0


@pytest.mark.parametrize("tool", DENIED_TOOLS)
def test_ferramentas_desligadas(tool: str):
    assert _front_matter()["tools"][tool] is False


@pytest.mark.parametrize("permission", DENIED_PERMISSIONS)
def test_permissoes_negadas(permission: str):
    assert _front_matter()["permission"][permission] == "deny"
