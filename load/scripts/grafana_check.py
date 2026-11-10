"""Confere que cada painel dos dashboards (09-04) devolve dados agora, pela API do Grafana.

Executa a consulta de cada alvo por `POST /api/ds/query` (o mesmo caminho do painel) nos últimos
15 minutos e conta as séries com ao menos um ponto. Uso: grafana_check.py --out <json>.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

DASHBOARDS = Path(__file__).resolve().parents[2] / "docker" / "grafana" / "dashboards"


def query(base: str, auth: str, expr: str, datasource: dict[str, str]) -> int:
    now = int(time.time() * 1000)
    body = {
        "from": str(now - 15 * 60 * 1000),
        "to": str(now),
        "queries": [{"refId": "A", "datasource": datasource, "expr": expr, "intervalMs": 15000}],
    }
    request = urllib.request.Request(  # noqa: S310 - Grafana local do operador
        f"{base}/api/ds/query",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        result: dict[str, Any] = json.load(response)["results"]["A"]
    if result.get("error"):
        raise RuntimeError(result["error"])
    series = 0
    for frame in result.get("frames", []):
        values = frame.get("data", {}).get("values", [])
        if len(values) >= 2 and any(v is not None for v in values[1]):
            series += 1
    return series


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--grafana", default=os.environ.get("GRAFANA_URL", "http://localhost:3001"))
    args = parser.parse_args()
    user = os.environ.get("GRAFANA_ADMIN_USER", "admin")
    password = os.environ.get("GRAFANA_ADMIN_PASSWORD", "dev-only-change-me")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    result: dict[str, Any] = {}
    for path in sorted(DASHBOARDS.glob("*.json")):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                key = f"{dashboard['uid']} | {panel['title']} | {target['refId']}"
                try:
                    result[key] = query(args.grafana, auth, target["expr"], target["datasource"])
                except Exception as error:  # noqa: BLE001 - registra e segue para o próximo painel
                    result[key] = f"erro: {error}"
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
