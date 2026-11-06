"""Sessão web assinada (ADR 0006): HMAC-SHA256, expiração e claims obrigatórios."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.domain.conversation.channel import Channel  # noqa: F401 - contrato de canais

pytestmark = pytest.mark.unit

SECRET = "segredo-web-teste"  # pragma: allowlist secret
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(hours=1)


def _sign(secret: str, token_payload: str) -> str:
    return hmac.new(secret.encode(), token_payload.encode(), hashlib.sha256).hexdigest()


def _forge(secret: str, claims: dict[str, object]) -> str:
    """Token no formato documentado `base64url(json).hex(hmac)`, com claims arbitrários."""
    raw = json.dumps(claims, sort_keys=True).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{payload}.{_sign(secret, payload)}"


def _sign_session(secret: str = SECRET, expires: datetime = EXPIRES) -> str:
    from commerce_agents.interfaces.webhooks.web import sign_web_session

    return sign_web_session(secret, "sess-1", "C0001", expires)


def _verify(secret: str, token: str, now: datetime = NOW):  # type: ignore[no-untyped-def]
    from commerce_agents.interfaces.webhooks.web import verify_web_session

    return verify_web_session(secret, token, now)


def test_ida_e_volta_preserva_as_claims():
    session = _verify(SECRET, _sign_session())

    assert session is not None
    assert session.session_id == "sess-1"
    assert session.customer_id == "C0001"


def test_sessao_expirada_devolve_none():
    token = _sign_session(expires=NOW - timedelta(seconds=1))

    assert _verify(SECRET, token) is None


def test_token_adulterado_devolve_none():
    token = _sign_session()
    payload, _, digest = token.partition(".")
    tampered = f"{payload}.{'0' if digest[0] != '0' else '1'}{digest[1:]}"

    assert _verify(SECRET, tampered) is None


def test_segredo_errado_devolve_none():
    assert _verify("outro-segredo", _sign_session()) is None


@pytest.mark.parametrize(
    "claims",
    [
        {"session_id": "sess-1", "expires_at": EXPIRES.isoformat()},
        {"customer_id": "C0001", "expires_at": EXPIRES.isoformat()},
        {"session_id": "sess-1", "customer_id": "C0001"},
        {},
    ],
)
def test_claims_faltando_devolvem_none(claims: dict[str, object]):
    assert _verify(SECRET, _forge(SECRET, claims)) is None


@given(st.text(max_size=200))
def test_verify_nunca_lanca_para_texto_arbitrario(token: str):
    assert _verify(SECRET, token) is None
