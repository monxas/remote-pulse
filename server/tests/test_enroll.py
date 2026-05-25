"""Tests for enrollment endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_enroll_success(client: AsyncClient, enrollment_token: str) -> None:
    """Test successful agent enrollment."""
    response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host",
            "group": "test-group",
            "host_fingerprint": "abc123",
            "os": "linux",
            "arch": "x86_64",
            "distro": "debian-12",
            "agent_version": "0.1.0",
        },
    )

    assert response.status_code == 201
    data = response.json()

    assert "host_id" in data
    assert "agent_config" in data
    assert data["agent_config"]["heartbeat_interval_s"] == 30


@pytest.mark.asyncio
async def test_enroll_invalid_token(client: AsyncClient) -> None:
    """Test enrollment with invalid JWT token."""
    response = await client.post(
        "/v1/enroll",
        json={
            "token": "invalid.jwt.token",
            "hostname": "test-host",
            "group": "test-group",
            "host_fingerprint": "abc123",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "0.1.0",
        },
    )

    assert response.status_code == 401
    assert "Invalid or expired" in response.json()["detail"]


@pytest.mark.asyncio
async def test_enroll_token_reuse(client: AsyncClient, enrollment_token: str) -> None:
    """Test that single-use token cannot be reused."""
    # First enrollment
    payload = {
        "token": enrollment_token,
        "hostname": "test-host-1",
        "group": "test-group",
        "host_fingerprint": "abc123",
        "os": "linux",
        "arch": "x86_64",
        "agent_version": "0.1.0",
    }

    response1 = await client.post("/v1/enroll", json=payload)
    assert response1.status_code == 201

    # Second enrollment with same token
    payload["hostname"] = "test-host-2"
    payload["host_fingerprint"] = "def456"

    response2 = await client.post("/v1/enroll", json=payload)
    assert response2.status_code == 403
    assert "exhausted" in response2.json()["detail"]
