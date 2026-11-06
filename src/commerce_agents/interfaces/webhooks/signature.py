"""Assinatura HMAC-SHA256 dos webhooks da Meta (`X-Hub-Signature-256`)."""

import hashlib
import hmac

_PREFIX = "sha256="


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Confere `sha256=<hex>` sobre o corpo BRUTO, em tempo constante."""
    if not header or not header.startswith(_PREFIX):
        return False
    received = header.removeprefix(_PREFIX)
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received.encode(), expected.encode())
