"""SDK do OpenTelemetry em memória, instalado uma vez no processo (o provider global é único)."""

from typing import Any

import pytest


@pytest.fixture(scope="session")
def _otel_sdk() -> tuple[Any, Any]:
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider
    from opentelemetry.sdk.metrics.export import AggregationTemporality, InMemoryMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)

    delta = AggregationTemporality.DELTA
    reader = InMemoryMetricReader(preferred_temporality={Counter: delta, Histogram: delta})
    metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))

    assert trace.get_tracer_provider() is tracer_provider, "outro TracerProvider global já existia"
    return exporter, reader


@pytest.fixture
def spans(_otel_sdk: tuple[Any, Any]) -> Any:
    """InMemorySpanExporter limpo para o teste."""
    exporter, _ = _otel_sdk
    exporter.clear()
    return exporter


@pytest.fixture
def metric_reader(_otel_sdk: tuple[Any, Any]) -> Any:
    """InMemoryMetricReader drenado: a próxima leitura só traz o que o teste produziu."""
    _, reader = _otel_sdk
    reader.get_metrics_data()
    return reader
