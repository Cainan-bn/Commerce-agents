"""Entidade de cliente."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Customer:
    """Cliente da loja."""

    customer_id: str
    name: str
    email: str
    phone: str
    created_at: datetime
