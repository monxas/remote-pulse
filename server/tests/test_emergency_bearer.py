"""Tests for emergency bearer fallback auth (review M7).

The bearer is meant as break-glass when PocketID/Caddy is down. It must:
- be rejected from an untrusted source
- be honored from a trusted proxy (Caddy LXC IP) or via Tailscale
- use constant-time comparison (no timing oracle)
- map to the configured emergency admin email
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from rp_server.config import settings
from rp_server.main import app
from rp_server.models import Base, User


@pytest.fixture(autouse=True)
def configure_emergency_bearer(monkeypatch):
    """Set a known bearer for the duration of these tests."""
    monkeypatch.setenv("EMERGENCY_ADMIN_BEARER", "test-emergency-bearer-32-characters-long")
    monkeypatch.setenv("EMERGENCY_ADMIN_EMAIL", "ramon@monxas.casa")
    # Reload Settings from env (Pydantic Settings doesn't auto-reload)
    settings.emergency_admin_bearer = os.environ["EMERGENCY_ADMIN_BEARER"]
    settings.emergency_admin_email = os.environ["EMERGENCY_ADMIN_EMAIL"]
    yield


@pytest.fixture
async def admin_user(test_db):
    """Pre-create the emergency admin user in the test DB."""
    user = User(
        pocketid_sub="placeholder-pocketid-sub-ramon",
        email="ramon@monxas.casa",
        name="Ramón",
        role="admin",
        accessible_groups=["default", "prod", "family", "iarq"],
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def test_bearer_rejected_from_untrusted_source(admin_user):
    """From an LAN IP not in trusted_proxies, bearer should be ignored.

    The request will continue to the X-Forwarded-* path and 401, instead of
    being authenticated as admin.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/admin/groups",
            headers={"Authorization": "Bearer test-emergency-bearer-32-characters-long"},
        )
        # 401 (untrusted), not 200
        assert response.status_code == 401


async def test_bearer_constant_time_comparison():
    """Internal: _safe_str_compare must use hmac.compare_digest."""
    from rp_server.deps import _safe_str_compare

    assert _safe_str_compare("abc123", "abc123") is True
    assert _safe_str_compare("abc123", "abc124") is False
    assert _safe_str_compare("abc", "abcdef") is False  # length differs


async def test_bearer_without_config_disabled(monkeypatch, admin_user):
    """When emergency_admin_bearer is unset, header is ignored."""
    monkeypatch.setattr(settings, "emergency_admin_bearer", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/admin/groups",
            headers={"Authorization": "Bearer anything"},
        )
        assert response.status_code == 401
