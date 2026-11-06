"""Entrada ASGI: ``uvicorn commerce_agents.interfaces.main:app`` (ou ``make run-api``)."""

from commerce_agents.interfaces.api import create_app  # pragma: no cover
from commerce_agents.interfaces.composition import Settings, build_api

app = create_app(build_api(Settings.from_env()))  # pragma: no cover
