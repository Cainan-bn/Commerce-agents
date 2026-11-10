"""Leitura do que o SDK do OpenTelemetry coletou em memória (spans e métricas).

Os imports do SDK ficam nas fixtures (tests/unit/observability/conftest.py): sem o pacote, cada
teste falha com ModuleNotFoundError em vez de quebrar a coleta.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def span_text(span: Any) -> str:
    """Tudo o que um span carrega em texto: nome, atributos, eventos e status."""
    parts = [span.name, str(span.status.description or "")]
    parts.extend(f"{key}={value}" for key, value in (span.attributes or {}).items())
    for event in span.events:
        parts.append(event.name)
        parts.extend(f"{key}={value}" for key, value in (event.attributes or {}).items())
    return "\n".join(parts)


def all_span_text(spans: Iterable[Any]) -> str:
    return "\n".join(span_text(span) for span in spans)


def ancestors(span: Any, spans: Iterable[Any]) -> list[Any]:
    """Cadeia de pais de `span` dentro de `spans`, do pai imediato até a raiz."""
    by_id = {s.context.span_id: s for s in spans}
    chain: list[Any] = []
    parent = span.parent
    while parent is not None and parent.span_id in by_id:
        current = by_id[parent.span_id]
        chain.append(current)
        parent = current.parent
    return chain


def collected(reader: Any) -> dict[str, list[Any]]:
    """Pontos de cada métrica desde a última leitura, por nome (delta: a leitura os consome)."""
    data = reader.get_metrics_data()
    result: dict[str, list[Any]] = {}
    if data is None:
        return result
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                result.setdefault(metric.name, []).extend(metric.data.data_points)
    return result
