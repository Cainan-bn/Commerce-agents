"""verify_signature (ADR 0006): HMAC-SHA256 do corpo, sha256=<hex>, tempo constante."""

import hashlib
import hmac
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.unit

SECRET = "segredo-de-teste"  # pragma: allowlist secret
BODY = b'{"object":"whatsapp_business_account"}'


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _verify(secret: str, body: bytes, header: str | None) -> bool:
    from commerce_agents.interfaces.webhooks.signature import verify_signature

    return verify_signature(secret, body, header)


def test_assinatura_valida_passa():
    assert _verify(SECRET, BODY, _sig(SECRET, BODY)) is True


def test_corpo_adulterado_falha():
    assert _verify(SECRET, BODY + b" ", _sig(SECRET, BODY)) is False


def test_segredo_errado_falha():
    assert _verify("outro-segredo", BODY, _sig(SECRET, BODY)) is False


@pytest.mark.parametrize(
    "header",
    [None, "", "sem-prefixo", "sha1=abcdef", "sha256=", "sha256=zz-nao-hex", "sha256 " + "0" * 64],
)
def test_header_ausente_ou_malformado_falha(header: str | None):
    assert _verify(SECRET, BODY, header) is False


def test_header_sem_prefixo_sha256_falha_mesmo_com_hex_correto():
    hex_digest = _sig(SECRET, BODY).removeprefix("sha256=")

    assert _verify(SECRET, BODY, hex_digest) is False


def test_comparacao_usa_hmac_compare_digest_em_tempo_constante(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[Any, Any]] = []
    original = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)

    assert _verify(SECRET, BODY, _sig(SECRET, BODY)) is True
    assert calls, "verify_signature precisa usar hmac.compare_digest"


@given(st.text(max_size=120))
def test_header_arbitrario_nunca_lanca(header: str):
    assert _verify(SECRET, BODY, header) in (True, False)
