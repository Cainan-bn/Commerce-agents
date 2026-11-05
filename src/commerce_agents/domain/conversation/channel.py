"""Canais de atendimento suportados."""

from enum import StrEnum


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    WEB = "web"
