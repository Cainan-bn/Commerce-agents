"""Base dos DTOs de fronteira: estritos, imutáveis e sem campos extras."""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
