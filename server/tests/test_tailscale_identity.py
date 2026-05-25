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
    assert "not from tailnet" in response.json()["detail"].lower()


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
    """Test that invalid email in Tailscale-User-Login returns 422."""
    response = await client.get(
        "/v1/hosts",
        headers={
            "Tailscale-User-Login": "not-an-email",
        },
    )

    # Pydantic EmailStr validation should reject
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_heartbeat_requires_tailscale_identity(client: AsyncClient, enrollment_token: str):
    """Test that heartbeat endpoint requires Tailscale identity."""
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

    assert heartbeat_response.status_code == 401

    # With Tailscale identity, should succeed
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
