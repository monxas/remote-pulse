"""Tests for Tailscale identity header extraction."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_tailscale_identity_present(client: AsyncClient):
    """Test that Tailscale identity headers are extracted correctly."""
    response = await client.get(
        "/v1/hosts",
        headers={
            "Tailscale-User-Login": "test@example.com",
            "Tailscale-User-Name": "Test User",
            "Tailscale-User-Profile-Pic": "https://example.com/pic.jpg",
            "Tailscale-Headers": "node=n123abc,cap=ssh",
        },
    )

    # Should succeed with valid identity (even if no hosts yet)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tailscale_identity_missing(client: AsyncClient):
    """Test that missing Tailscale identity headers return 401."""
    response = await client.get("/v1/hosts")

    assert response.status_code == 401
    # /v1/hosts accepts EITHER a tailnet identity OR a logged-in PocketID user
    # (tailscale_identity_optional + current_user_optional), so the combined
    # rejection message is "Authentication required". The old assertion looked
    # for "not from tailnet", which is what the strict-only dependency said
    # before the endpoint grew the second auth path.
    assert "authentication required" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tailscale_identity_partial_headers(client: AsyncClient):
    """Test with minimal required headers (only login)."""
    response = await client.get(
        "/v1/hosts",
        headers={
            "Tailscale-User-Login": "test@example.com",
        },
    )

    # Should succeed with just login header
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tailscale_identity_invalid_email(client: AsyncClient):
    """A malformed Tailscale-User-Login must not reach the handler.

    This used to let pydantic's ValidationError escape the dependency, which
    FastAPI reports as an unhandled 500 (the test expected 422 and got a raw
    exception). Both dependencies now catch it: the optional one degrades to
    "no identity", so /v1/hosts answers 401 rather than crashing.
    """
    response = await client.get(
        "/v1/hosts",
        headers={
            "Tailscale-User-Login": "not-an-email",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_heartbeat_accepts_unauthenticated_writes(
    client: AsyncClient, enrollment_token: str
):
    """POST /v1/heartbeat is deliberately unauthenticated today.

    This test was written as `test_heartbeat_requires_tailscale_identity` and
    asserted 401 without identity headers. The handler does the opposite, on
    purpose and in writing: it takes `tailscale_identity_optional` and its
    docstring says "F1: No authentication enforcement (HTTP plaintext LAN).
    F2 TODO: Verify Tailscale identity matches host ownership."

    So the test asserted a requirement that was never implemented. It now pins
    the contract that actually ships, because the alternative -- enforcing
    identity on heartbeat -- would instantly mute every agent in the fleet
    (they send no identity header) and is a coordinated agent+server rollout,
    not a test fix.

    SECURITY GAP, reported separately: anything that can reach :8080 can forge
    a heartbeat for any known host_id, which is enough to keep an offline host
    looking online. Tracked for the F2 auth work, NOT closed by this test.
    """
    # First enroll a host (enrollment is public, no TS required yet in F2)
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host",
            "group": "test",
            "host_fingerprint": "test-fingerprint-123",
            "os": "linux",
            "arch": "x86_64",
            "distro": "debian-12",
            "agent_version": "0.1.0",
        },
    )
    assert enroll_response.status_code == 201
    host_id = enroll_response.json()["host_id"]

    # Try heartbeat without Tailscale identity
    heartbeat_response = await client.post(
        "/v1/heartbeat",
        json={
            "host_id": host_id,
            "cpu_pct": 50.0,
            "mem_pct": 60.0,
            "agent_version": "0.1.0",
        },
    )

    # Documented current behaviour: accepted without any identity.
    assert heartbeat_response.status_code == 200

    # With Tailscale identity, also succeeds (identity is recorded, not required).
    heartbeat_response = await client.post(
        "/v1/heartbeat",
        json={
            "host_id": host_id,
            "cpu_pct": 50.0,
            "mem_pct": 60.0,
            "agent_version": "0.1.0",
        },
        headers={
            "Tailscale-User-Login": "test@example.com",
        },
    )

    assert heartbeat_response.status_code == 200
