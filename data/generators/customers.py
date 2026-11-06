"""Geração determinística dos clientes fictícios da TH Multimarcas."""

from __future__ import annotations

import random
import unicodedata
from datetime import UTC, datetime, timedelta

from data.generators.models import Customer

CUSTOMER_COUNT = 200

FIRST_NAMES: tuple[str, ...] = (
    "Ana",
    "João",
    "Maria",
    "Carlos",
    "Beatriz",
    "Pedro",
    "Fernanda",
    "Lucas",
    "Juliana",
    "Rafael",
    "Camila",
    "Bruno",
    "Patrícia",
    "Felipe",
    "Larissa",
    "Gustavo",
    "Amanda",
    "Rodrigo",
    "Tatiane",
    "Thiago",
    "Renata",
    "André",
    "Bruna",
    "Vinícius",
    "Carla",
    "Diego",
    "Letícia",
    "Eduardo",
    "Priscila",
    "Marcelo",
    "Vanessa",
    "Ricardo",
    "Aline",
    "Alexandre",
    "Carolina",
    "Sérgio",
    "Débora",
    "Otávio",
    "Elaine",
    "Paulo",
    "Michele",
    "Fábio",
    "Suelen",
    "Leandro",
    "Natália",
    "Roberto",
    "Luana",
    "Danilo",
    "Tainá",
    "Wilson",
)

SURNAMES: tuple[str, ...] = (
    "Souza",
    "Oliveira",
    "Santos",
    "Pereira",
    "Costa",
    "Rodrigues",
    "Almeida",
    "Nascimento",
    "Lima",
    "Araújo",
    "Fernandes",
    "Carvalho",
    "Gomes",
    "Martins",
    "Rocha",
    "Ribeiro",
    "Alves",
    "Monteiro",
    "Mendes",
    "Barbosa",
    "Cardoso",
    "Teixeira",
    "Correia",
    "Farias",
    "Moraes",
    "Vieira",
    "Nogueira",
    "Cavalcanti",
    "Pinto",
    "Freitas",
)

_CREATED_FROM = datetime(2025, 1, 1, tzinfo=UTC)
_CREATED_TO = datetime(2026, 9, 30, tzinfo=UTC)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _random_datetime(rng: random.Random, start: datetime, end: datetime) -> datetime:
    span_days = (end - start).days
    day = start + timedelta(days=rng.randint(0, span_days))
    return day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59), second=0, microsecond=0)


def generate_customers(rng: random.Random) -> list[Customer]:
    """Gera ~200 clientes com dados de contato 100% fictícios."""
    customers: list[Customer] = []
    used_names: set[str] = set()
    email_counts: dict[str, int] = {}

    for index in range(1, CUSTOMER_COUNT + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(SURNAMES)
        name = f"{first} {last}"
        while name in used_names:
            last = rng.choice(SURNAMES)
            name = f"{first} {last}"
        used_names.add(name)

        base = f"{_strip_accents(first)}.{_strip_accents(last)}".lower()
        email_counts[base] = email_counts.get(base, 0) + 1
        occurrence = email_counts[base]
        email = f"{base}@example.com" if occurrence == 1 else f"{base}{occurrence}@example.com"

        customers.append(
            Customer(
                customer_id=f"C{index:04d}",
                name=name,
                email=email,
                phone=f"+5511 90000-{index:04d}",
                created_at=_random_datetime(rng, _CREATED_FROM, _CREATED_TO),
            )
        )
    return customers
