"""Sessão web assinada: `base64url(json).hex(hmac)` com expiração (ADR 0014)."""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WebSession:
    session_id: str
    customer_id: str
    expires_at: datetime


def _mac(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign_web_session(secret: str, session_id: str, customer_id: str, expires_at: datetime) -> str:
    claims = {
        "session_id": session_id,
        "customer_id": customer_id,
        "expires_at": expires_at.isoformat(),
    }
    raw = json.dumps(claims, sort_keys=True).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{payload}.{_mac(secret, payload)}"


def verify_web_session(secret: str, token: str, now: datetime) -> WebSession | None:
    """Sessão válida ou `None` (assinatura, claims ou expiração inválidos). Nunca lança."""
    payload, _, digest = token.partition(".")
    if not payload or not hmac.compare_digest(digest.encode(), _mac(secret, payload).encode()):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        session_id, customer_id = claims["session_id"], claims["customer_id"]
        expires_at = datetime.fromisoformat(claims["expires_at"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return None
    if not (isinstance(session_id, str) and isinstance(customer_id, str)) or expires_at <= now:
        return None
    return WebSession(session_id, customer_id, expires_at)
