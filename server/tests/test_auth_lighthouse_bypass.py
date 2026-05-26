"""Tests for the Lighthouse CI auth bypass (ADR-0009 Phase 5).

The bypass is gated on TWO conditions that both must hold:
    1. Env var ``RP_LIGHTHOUSE_BYPASS_TOKEN`` is set (server opt-in).
    2. Request carries header ``X-RP-Test-Auth: <that token>``.

If either is missing, behavior must fall through to the normal auth chain.
The env-gate is what makes a stray header in prod harmless: even if some
LAN client guesses or replays the header, the prod server has no env var
configured and the check is a no-op.

These tests exercise the four matrix corners (env-set × header-correct).
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from rp_server.main import app


@pytest.fixture
def lh_token() -> str:
    return "test-lh-bypass-token-deadbeef-cafef00d-32chars"


# ---------------------------------------------------------------------------
# /auth/me — easiest target: no DB, no trusted-proxy gate
# ---------------------------------------------------------------------------


async def test_no_env_var_header_ignored(monkeypatch, lh_token):
    """Without the env var, the bypass header must be a no-op (unauthenticated)."""
    monkeypatch.delenv("RP_LIGHTHOUSE_BYPASS_TOKEN", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/me", headers={"X-RP-Test-Auth": lh_token})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


async def test_env_set_correct_header_grants_synth_user(monkeypatch, lh_token):
    """With env var + matching header, bypass returns a synthetic admin."""
    monkeypatch.setenv("RP_LIGHTHOUSE_BYPASS_TOKEN", lh_token)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/me", headers={"X-RP-Test-Auth": lh_token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user_email"] == "lighthouse@test"
        assert body["user_role"] == "admin"


async def test_env_set_wrong_header_rejects(monkeypatch, lh_token):
    """With env var but wrong header value, bypass must NOT activate."""
    monkeypatch.setenv("RP_LIGHTHOUSE_BYPASS_TOKEN", lh_token)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/auth/me", headers={"X-RP-Test-Auth": "obviously-wrong-token"}
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


async def test_env_set_no_header_no_bypass(monkeypatch, lh_token):
    """With env var set but no header, normal session path runs."""
    monkeypatch.setenv("RP_LIGHTHOUSE_BYPASS_TOKEN", lh_token)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


# ---------------------------------------------------------------------------
# current_user dep — exercised via an authed v1 endpoint
# ---------------------------------------------------------------------------


async def test_current_user_bypass_grants_authed_route(monkeypatch, lh_token, client):
    """A real authed endpoint must accept the synthetic admin from bypass.

    /v1/dash/me uses current_user as a dependency. With env + header set,
    bypass should activate and the handler should see the synthetic user.
    """
    monkeypatch.setenv("RP_LIGHTHOUSE_BYPASS_TOKEN", lh_token)

    resp = await client.get(
        "/v1/dash/me", headers={"X-RP-Test-Auth": lh_token}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "lighthouse@test"
    assert body["role"] == "admin"


async def test_current_user_no_env_var_rejects_bypass_header(lh_token, client):
    """Without env var, the header on a real authed endpoint is ignored."""
    # Ensure env unset (in case earlier test forgot to clean up)
    os.environ.pop("RP_LIGHTHOUSE_BYPASS_TOKEN", None)

    resp = await client.get(
        "/v1/dash/me", headers={"X-RP-Test-Auth": lh_token}
    )
    assert resp.status_code == 401


async def test_current_user_wrong_token_rejected(monkeypatch, lh_token, client):
    """Env set + wrong token → 401, not bypass."""
    monkeypatch.setenv("RP_LIGHTHOUSE_BYPASS_TOKEN", lh_token)

    resp = await client.get(
        "/v1/dash/me", headers={"X-RP-Test-Auth": "wrong-token"}
    )
    assert resp.status_code == 401
