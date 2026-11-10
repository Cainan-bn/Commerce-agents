"""Entrada ASGI: ``uvicorn commerce_agents.interfaces.main:app`` (ou ``make run-api``)."""

import os  # pragma: no cover

from commerce_agents.interfaces.api import create_app  # pragma: no cover
from commerce_agents.interfaces.composition import Settings, build_api  # pragma: no cover
from commerce_agents.interfaces.telemetry import (  # pragma: no cover
    configure_logging,
    setup_telemetry,
)

configure_logging(os.environ.get("LOG_LEVEL", "INFO"))  # pragma: no cover
setup_telemetry(os.environ)  # pragma: no cover
app = create_app(build_api(Settings.from_env()))  # pragma: no cover
