"""Legacy HS512 compatibility without using python-jose or a live service."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from jwt import InvalidTokenError

from rp_server.auth import create_enrollment_token, decode_enrollment_token
from rp_server.config import settings
from rp_server.models import Enrollment


@pytest.fixture(autouse=True)
def synthetic_signing_key(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "synthetic-enrollment-key-" * 3)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS512")


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _legacy_payload(**changes):
    now = int(time.time())
    return {
        "jti": "legacy-jti",
        "iat": now,
        "exp": now + 3600,
        "group_name": "test-group",
        "issued_by": "test-admin",
        "max_uses": 1,
        **changes,
    }


def _legacy_token(payload, algorithm="HS512", key=None):
    # JWT/JWS compact format emitted by the old encoder, signed independently.
    header = _b64(json.dumps({"typ": "JWT", "alg": algorithm}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing = f"{header}.{body}"
    digest = hashlib.sha512 if algorithm == "HS512" else hashlib.sha256
    signature = hmac.new((key or settings.jwt_secret).encode(), signing.encode(), digest).digest()
    return f"{signing}.{_b64(signature)}"


def test_legacy_hs512_token_decodes_with_unchanged_claims():
    payload = _legacy_payload()
    assert decode_enrollment_token(_legacy_token(payload)) == payload


def test_new_token_is_independently_verifiable_and_preserves_ttl():
    token, jti = create_enrollment_token("test-group", "test-admin", max_uses=3)
    header, body, signature = token.split(".")
    assert json.loads(_unb64(header))["alg"] == "HS512"
    expected = hmac.new(settings.jwt_secret.encode(), f"{header}.{body}".encode(), hashlib.sha512)
    assert hmac.compare_digest(_unb64(signature), expected.digest())
    payload = json.loads(_unb64(body))
    assert payload["exp"] - payload["iat"] == 24 * 3600
    assert payload["jti"] == jti
    assert payload["group_name"] == "test-group"
    assert payload["issued_by"] == "test-admin"
    assert payload["max_uses"] == 3
    assert decode_enrollment_token(token) == payload


@pytest.mark.parametrize("iat", ["123", 123.75])
def test_legacy_integer_conversion_for_iat_is_preserved(iat):
    # The old validator called int(iat), including numeric strings/floats.
    payload = _legacy_payload(iat=iat)
    assert decode_enrollment_token(_legacy_token(payload)) == payload


def test_legacy_future_iat_is_not_a_new_not_before_constraint():
    payload = _legacy_payload(iat=int(time.time()) + 600)
    assert decode_enrollment_token(_legacy_token(payload)) == payload


@pytest.mark.parametrize("case", ["signature", "algorithm", "expired", "nbf", "iat", "malformed"])
def test_invalid_tokens_rejected(case):
    payload = _legacy_payload()
    if case == "signature":
        token = _legacy_token(payload, key="wrong-signing-key" * 4)
    elif case == "algorithm":
        token = _legacy_token(payload, algorithm="HS256")
    elif case == "expired":
        token = _legacy_token({**payload, "exp": int(time.time()) - 60})
    elif case == "nbf":
        token = _legacy_token({**payload, "nbf": int(time.time()) + 600})
    elif case == "iat":
        token = _legacy_token({**payload, "iat": "not-an-integer"})
    else:
        token = "invalid.jwt.token"
    with pytest.raises(InvalidTokenError):
        decode_enrollment_token(token)


@pytest.mark.parametrize("case", ["signature", "algorithm", "expired", "iat"])
async def test_api_invalid_token_keeps_401_contract(client, case):
    payload = _legacy_payload()
    kwargs = {}
    if case == "signature":
        kwargs["key"] = "wrong-key" * 8
    elif case == "algorithm":
        kwargs["algorithm"] = "HS256"
    elif case == "expired":
        payload["exp"] = int(time.time()) - 60
    else:
        payload["iat"] = "bad"
    response = await client.post(
        "/v1/enroll",
        json={
            "token": _legacy_token(payload, **kwargs),
            "hostname": "synthetic-host",
            "host_fingerprint": "synthetic-fingerprint",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired enrollment token"


async def test_legacy_token_enrolls_against_existing_record(client, db_session):
    payload = _legacy_payload()
    db_session.add(
        Enrollment(
            token_jti=payload["jti"],
            issued_by="test-admin",
            group_name="test-group",
            max_uses=1,
            used_count=0,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()
    response = await client.post(
        "/v1/enroll",
        json={
            "token": _legacy_token(payload),
            "hostname": "legacy-host",
            "host_fingerprint": "legacy-fingerprint",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 201


async def test_missing_required_claim_keeps_400_contract(client):
    payload = _legacy_payload()
    del payload["group_name"]
    response = await client.post(
        "/v1/enroll",
        json={
            "token": _legacy_token(payload),
            "hostname": "synthetic-host",
            "host_fingerprint": "synthetic-fingerprint",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 400
    assert "Missing required claims" in response.json()["detail"]


def _nested_token(valid_signature):
    header = _b64(b'{"typ":"JWT","alg":"HS512"}')
    # Build raw JSON without recursively serialising it in the test itself.
    depth = 10_000  # Exceeds both Python and CPython 3.12 C-JSON recursion limits.
    body = _b64(b'{"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}")
    signing = f"{header}.{body}"
    key = settings.jwt_secret if valid_signature else "wrong-key" * 8
    signature = hmac.new(key.encode(), signing.encode(), hashlib.sha512).digest()
    return f"{signing}.{_b64(signature)}"


@pytest.mark.parametrize("valid_signature", [False, True])
def test_nested_payload_is_invalid_token_not_recursion_error(valid_signature):
    with pytest.raises(InvalidTokenError):
        decode_enrollment_token(_nested_token(valid_signature))


@pytest.mark.parametrize("valid_signature", [False, True])
async def test_api_nested_payload_returns_401(client, valid_signature):
    response = await client.post(
        "/v1/enroll",
        json={
            "token": _nested_token(valid_signature),
            "hostname": "synthetic-host",
            "host_fingerprint": "synthetic-fingerprint",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired enrollment token"


@pytest.mark.parametrize("claim", ["exp", "nbf", "iat"])
@pytest.mark.parametrize("value", [None, [], {}])
def test_non_numeric_temporal_claims_raise_invalid_token(claim, value):
    with pytest.raises(InvalidTokenError):
        decode_enrollment_token(_legacy_token(_legacy_payload(**{claim: value})))


@pytest.mark.parametrize("claim", ["exp", "nbf", "iat"])
@pytest.mark.parametrize("value", [None, [], {}])
async def test_api_non_numeric_temporal_claims_return_401(client, claim, value):
    response = await client.post(
        "/v1/enroll",
        json={
            "token": _legacy_token(_legacy_payload(**{claim: value})),
            "hostname": "synthetic-host",
            "host_fingerprint": "synthetic-fingerprint",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "1.0.0",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired enrollment token"


def test_legacy_token_with_padded_signature_still_verifies():
    payload = _legacy_payload()
    token = _legacy_token(payload)
    header, body, signature = token.split(".")
    signature += "=" * (-len(signature) % 4)
    assert decode_enrollment_token(f"{header}.{body}.{signature}") == payload
