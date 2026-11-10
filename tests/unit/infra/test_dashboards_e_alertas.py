"""Dashboards do Grafana e alertas do Prometheus como código (TASK-09-04).

Os nomes de métricas aceitos vêm de docker/grafana/dashboards/METRICAS.md, levantados no
Prometheus real; consultas com nome inventado ou label de alta cardinalidade falham aqui.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
DASHBOARDS = ROOT / "docker" / "grafana" / "dashboards"
PROVISIONING = ROOT / "docker" / "grafana" / "provisioning"
PROMETHEUS = ROOT / "docker" / "prometheus"
COMPOSE = ROOT / "docker-compose.yml"
EXPECTED = {"atendimento.json", "llm.json", "ferramentas.json"}
FORBIDDEN_LABELS = ("conversation_id", "customer_id", "message_id")

# Funções, agregações e palavras-chave do PromQL usadas nas consultas.
PROMQL_WORDS = {
    "sum", "avg", "min", "max", "count", "by", "without", "rate", "irate", "increase",
    "histogram_quantile", "clamp_min", "clamp_max", "abs", "and", "or", "unless", "on",
    "ignoring", "group_left", "group_right", "bool", "offset", "le", "vector", "scalar",
}  # fmt: skip


def _metric_names() -> set[str]:
    text = (DASHBOARDS / "METRICAS.md").read_text(encoding="utf-8")
    names = set(re.findall(r"`([a-z][a-zA-Z0-9_]*_(?:total|bucket|sum|count))`", text))
    assert names, "METRICAS.md sem nomes do Prometheus"
    return names


def _dashboards() -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DASHBOARDS.glob("*.json"))
    }


def _panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    for panel in dashboard.get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def _targets() -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{name}:{panel['title']}", target)
        for name, dashboard in _dashboards().items()
        for panel in _panels(dashboard)
        for target in panel.get("targets", [])
    ]


def _alert_exprs() -> list[tuple[str, str]]:
    rules = yaml.safe_load((PROMETHEUS / "rules" / "commerce.yml").read_text(encoding="utf-8"))
    return [
        (rule["alert"], rule["expr"])
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]


def _identifiers(expr: str) -> set[str]:
    """Identificadores da consulta fora de seletores, janelas, `by (...)` e literais."""
    stripped = re.sub(r"\{[^}]*\}", " ", expr)
    stripped = re.sub(r"\[[^\]]*\]", " ", stripped)
    stripped = re.sub(r"\boffset\s+\d+[smhdwy]+", " ", stripped)
    stripped = re.sub(r"\b(by|without|on|ignoring)\s*\([^)]*\)", " ", stripped)
    stripped = re.sub(r'"[^"]*"', " ", stripped)
    return set(re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", stripped)) - PROMQL_WORDS


def _all_exprs() -> list[tuple[str, str]]:
    return [(where, target["expr"]) for where, target in _targets()] + _alert_exprs()


def test_existem_os_tres_dashboards():
    assert EXPECTED <= set(_dashboards())


def test_paineis_e_alertas_usam_so_metricas_do_metricas_md():
    known = _metric_names()
    for where, expr in _all_exprs():
        identifiers = _identifiers(expr)
        assert identifiers, f"{where}: consulta sem métrica"
        assert identifiers <= known, f"{where}: métricas fora do METRICAS.md: {identifiers - known}"


def test_nenhuma_consulta_usa_label_de_alta_cardinalidade():
    for where, expr in _all_exprs():
        for label in FORBIDDEN_LABELS:
            assert label not in expr, f"{where}: {label}"
    for where, target in _targets():
        legend = str(target.get("legendFormat", ""))
        assert not any(label in legend for label in FORBIDDEN_LABELS), where


def test_uids_fixos_e_unicos_sem_id_nem_versao_de_instancia():
    dashboards = _dashboards()
    uids = [dashboard.get("uid") for dashboard in dashboards.values()]

    assert all(isinstance(uid, str) and uid for uid in uids)
    assert len(set(uids)) == len(uids)
    for name, dashboard in dashboards.items():
        assert "id" not in dashboard, name
        assert "version" not in dashboard, name


def test_datasource_sempre_pelo_uid_provisionado():
    datasources = yaml.safe_load(
        (PROVISIONING / "datasources" / "prometheus.yml").read_text(encoding="utf-8")
    )["datasources"]
    uid = next(ds["uid"] for ds in datasources if ds["type"] == "prometheus")

    for name, dashboard in _dashboards().items():
        for panel in _panels(dashboard):
            for ref in [panel.get("datasource"), *(t.get("datasource") for t in panel["targets"])]:
                assert ref == {"type": "prometheus", "uid": uid}, f"{name}:{panel['title']}"


def _mounts(service: str) -> dict[str, str]:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    mounts: dict[str, str] = {}
    for volume in compose["services"][service].get("volumes", []):
        source, target = str(volume).split(":")[:2]
        mounts[target] = source
    return mounts


def test_provisioning_aponta_para_o_diretorio_montado():
    provider = yaml.safe_load(
        (PROVISIONING / "dashboards" / "dashboards.yml").read_text(encoding="utf-8")
    )["providers"][0]
    mounts = _mounts("grafana")

    path = provider["options"]["path"]
    assert path in mounts
    assert (ROOT / mounts[path]).resolve() == DASHBOARDS.resolve()


def test_prometheus_carrega_as_regras_montadas():
    config = yaml.safe_load((PROMETHEUS / "prometheus.yml").read_text(encoding="utf-8"))
    mounts = _mounts("prometheus")

    (pattern,) = config["rule_files"]
    rules_dir = str(Path(pattern).parent)
    assert rules_dir in mounts
    assert (ROOT / mounts[rules_dir]).resolve() == (PROMETHEUS / "rules").resolve()


def test_alertas_contratados_existem():
    alerts = dict(_alert_exprs())

    assert {"TurnoLentoP95", "CircuitoLLMAberto", "TaxaErroLLMAlta"} <= set(alerts)
    assert "> 4" in alerts["TurnoLentoP95"]
    assert "> 0.2" in alerts["TaxaErroLLMAlta"]


def test_teste_de_regras_promtool_esta_versionado_e_aponta_para_as_regras():
    test_file = PROMETHEUS / "tests" / "commerce.test.yml"
    data = yaml.safe_load(test_file.read_text(encoding="utf-8"))

    for rule_file in data["rule_files"]:
        assert (test_file.parent / rule_file).resolve() == (
            PROMETHEUS / "rules" / "commerce.yml"
        ).resolve()
    tested = {t["alertname"] for case in data["tests"] for t in case["alert_rule_test"]}
    assert tested == {"TurnoLentoP95", "CircuitoLLMAberto", "TaxaErroLLMAlta"}
