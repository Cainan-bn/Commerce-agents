"""Setup do SDK OpenTelemetry e do formato de log na composição (ADR 0018).

Só instala o SDK com `OTEL_EXPORTER_OTLP_ENDPOINT`; sem ele a API segue no-op (testes, eval e
desenvolvimento sem collector não mudam). O endpoint não é logado.
"""

import logging
from collections.abc import Mapping

from commerce_agents.infrastructure.telemetry import TraceContextLogFilter
from commerce_agents.interfaces.log_redaction import RedactQueryTokens

DEFAULT_SERVICE_NAME = "commerce-agents"
# Loggers do uvicorn que escrevem o caminho com a query (acesso HTTP e linhas de WebSocket).
REDACTED_LOGGERS = ("uvicorn.access", "uvicorn.error")
LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "trace_id=%(trace_id)s conversation_id=%(conversation_id)s %(message)s"
)


def setup_telemetry(environ: Mapping[str, str]) -> bool:
    """Instala TracerProvider e MeterProvider do SDK com exportação OTLP; `False` sem endpoint."""
    endpoint = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": environ.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME}
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(tracer_provider)
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    return True


def configure_logging(level: str = "INFO") -> None:
    """Log de texto com `trace_id` e `conversation_id` em toda linha (sem texto do cliente).

    Instala também, sem duplicar, o filtro que esconde tokens da query nos logs do uvicorn.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, TraceContextLogFilter) for f in handler.filters):
            handler.addFilter(TraceContextLogFilter())
    for name in REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactQueryTokens) for f in logger.filters):
            logger.addFilter(RedactQueryTokens())
