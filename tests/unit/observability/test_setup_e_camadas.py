"""Setup do SDK na composição e fronteira das camadas (ADR 0018).

- `commerce_agents.interfaces.telemetry.setup_telemetry(environ) -> bool`: sem
  `OTEL_EXPORTER_OTLP_ENDPOINT` não instala nada (devolve False e os providers globais seguem
  no-op); com ele, instala TracerProvider e MeterProvider do SDK e devolve True. Roda em
  subprocesso: o provider global é único por processo e as fixtures deste pacote já o ocupam.
- import-linter: `domain` e `application` não importam `opentelemetry`.
"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]

SCRIPT = """
import os, sys
from commerce_agents.interfaces.telemetry import setup_telemetry
installed = setup_telemetry(dict(os.environ))
from opentelemetry import metrics, trace
print(installed, type(trace.get_tracer_provider()).__name__,
      type(metrics.get_meter_provider()).__name__, flush=True)
os._exit(0)  # sem atexit: não tenta exportar para um collector que não existe
"""


def _run(extra_env: dict[str, str]) -> list[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    env.update(extra_env)
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


def test_sem_endpoint_otlp_nao_instala_sdk_e_providers_seguem_no_op():
    installed, tracer_provider, meter_provider = _run({})

    assert installed == "False"
    assert tracer_provider == "ProxyTracerProvider"
    assert meter_provider in {"_ProxyMeterProvider", "NoOpMeterProvider"}


def test_com_endpoint_otlp_instala_tracer_e_meter_do_sdk():
    installed, tracer_provider, meter_provider = _run(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4317"}
    )

    assert installed == "True"
    assert tracer_provider == "TracerProvider"
    assert meter_provider == "MeterProvider"


@pytest.mark.parametrize("layer", ["commerce_agents.domain", "commerce_agents.application"])
def test_import_linter_proibe_opentelemetry_em_domain_e_application(layer: str):
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]

    proibidos = [
        c
        for c in contracts
        if c["type"] == "forbidden"
        and layer in c["source_modules"]
        and "opentelemetry" in c["forbidden_modules"]
    ]

    assert proibidos, f"nenhum contrato forbidden impede {layer} de importar opentelemetry"
