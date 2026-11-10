"""Langfuse opcional no collector (Fase 09): a base não o conhece; o overlay o liga.

Contrato fixado:
- `docker/otel/otel-collector.yaml` (base) sem exporter nem pipeline do Langfuse;
- `docker/otel/otel-collector.langfuse.yaml` acrescenta `otlphttp/langfuse` e o pipeline
  `traces/langfuse` (só spans `llm.complete`), lendo a credencial só de `${env:...}`;
- `docker-compose.langfuse.yml` passa os dois `--config` ao `otel-collector`;
- alvo `make up-langfuse` sobe a stack com o override; `.env.example` documenta a credencial.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "docker" / "otel" / "otel-collector.yaml"
OVERLAY = ROOT / "docker" / "otel" / "otel-collector.langfuse.yaml"
COMPOSE = ROOT / "docker-compose.yml"
COMPOSE_LANGFUSE = ROOT / "docker-compose.langfuse.yml"
ENV_REF = re.compile(r"\$\{env:LANGFUSE_OTLP_AUTH\}")


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _merge(base: Any, overlay: Any) -> Any:
    """Como o collector junta vários `--config`: mapas se fundem, o resto é substituído."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = _merge(base[key], value) if key in base else value
        return merged
    return overlay


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _strings(value)]
    return [node] if isinstance(node, str) else []


def test_base_nao_referencia_langfuse():
    assert "langfuse" not in BASE.read_text(encoding="utf-8").lower()


def test_base_mantem_jaeger_e_prometheus():
    pipelines = _load(BASE)["service"]["pipelines"]

    assert pipelines["traces"]["exporters"] == ["otlp/jaeger"]
    assert pipelines["metrics"]["exporters"] == ["prometheus"]


def test_base_mais_overlay_tem_o_pipeline_do_langfuse():
    config = _merge(_load(BASE), _load(OVERLAY))
    pipelines = config["service"]["pipelines"]

    assert "otlphttp/langfuse" in config["exporters"]
    langfuse = pipelines["traces/langfuse"]
    assert langfuse["receivers"] == ["otlp"]
    assert langfuse["exporters"] == ["otlphttp/langfuse"]
    filters = [p for p in langfuse["processors"] if p.startswith("filter")]
    assert len(filters) == 1
    assert 'name != "llm.complete"' in config["processors"][filters[0]]["traces"]["span"]
    # O overlay acrescenta; o trace completo continua indo para o Jaeger.
    assert pipelines["traces"]["exporters"] == ["otlp/jaeger"]
    assert pipelines["metrics"]["exporters"] == ["prometheus"]


def test_overlay_so_le_a_credencial_do_ambiente():
    overlay = _load(OVERLAY)
    headers = overlay["exporters"]["otlphttp/langfuse"]["headers"]

    assert ENV_REF.search(headers["Authorization"])
    sensitive = [s for s in _strings(overlay) if "Basic" in s or "LANGFUSE_OTLP_AUTH" in s]
    assert sensitive
    assert all(ENV_REF.search(s) for s in sensitive)
    assert not re.search(r"(pk|sk)-lf-", OVERLAY.read_text(encoding="utf-8"))


def _volumes(service: dict[str, Any]) -> dict[str, str]:
    """Destino no container -> origem no host, das montagens curtas `origem:destino[:ro]`."""
    mounts: dict[str, str] = {}
    for volume in service.get("volumes", []):
        source, target = str(volume).split(":")[:2]
        mounts[target] = source
    return mounts


def test_override_passa_os_dois_configs_ao_collector():
    base = _load(COMPOSE)["services"]["otel-collector"]
    override = _load(COMPOSE_LANGFUSE)["services"]["otel-collector"]
    mounts = {**_volumes(base), **_volumes(override)}

    configs = [
        arg.removeprefix("--config=file:")
        for arg in override["command"]
        if str(arg).startswith("--config=file:")
    ]

    assert len(configs) == 2
    sources = {Path(mounts[target]).name for target in configs}
    assert sources == {BASE.name, OVERLAY.name}
    assert configs[0] == base["command"][0].removeprefix("--config=file:")


def test_override_entrega_a_credencial_ao_collector():
    override = _load(COMPOSE_LANGFUSE)["services"]["otel-collector"]
    environment = override.get("environment", {})

    assert "LANGFUSE_OTLP_AUTH" in environment


def test_make_up_langfuse_usa_o_override():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^up-langfuse:.*?(?=^\S|\Z)", makefile, flags=re.M | re.S)

    assert match, "alvo up-langfuse ausente"
    recipe = match.group(0)
    assert "-f docker-compose.yml" in recipe
    assert "-f docker-compose.langfuse.yml" in recipe


def test_env_example_documenta_a_credencial():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert re.search(r"^#.*[Ll]angfuse.*$\n(#.*\n)*LANGFUSE_OTLP_AUTH=", text, flags=re.M)
    assert "make up-langfuse" in text
