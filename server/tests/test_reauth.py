"""Tests for agent re-authentication endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from rp_server.integrations.tailscale_api import TailscaleAuthKeyResponse


@pytest.mark.asyncio
async def test_reauth_host_not_found(client: AsyncClient):
    """Test reauth with non-existent host ID."""
    response = await client.post(
        "/v1/agent/reauth",
        json={
            "host_id": "00000000-0000-0000-0000-000000000000",
            "machine_fingerprint": "test-fingerprint",
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reauth_invalid_host_id_format(client: AsyncClient):
    """Test reauth with invalid UUID format."""
    response = await client.post(
        "/v1/agent/reauth",
        json={
            "host_id": "not-a-uuid",
            "machine_fingerprint": "test-fingerprint",
        },
    )

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reauth_success_with_tailscale_api(client: AsyncClient, enrollment_token: str):
    """Test successful reauth with Tailscale API key configured."""
    # First enroll a host
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host-reauth",
            "group": "prod",
            "host_fingerprint": "test-fingerprint-reauth",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "0.1.0",
        },
    )
    assert enroll_response.status_code == 201
    host_id = enroll_response.json()["host_id"]

    # Mock Tailscale API response
    mock_response = TailscaleAuthKeyResponse(
        id="k789012",
        key="tskey-auth-reauth-xxxxxxxxxxxxxxxxxxxxxxxx",
        created="2026-05-25T12:00:00Z",
        expires="2026-05-26T12:00:00Z",
        revoked=False,
        capabilities={"devices": {"create": {"ephemeral": True}}},
        description="rp reauth test-host-reauth",
    )

    with patch("rp_server.config.settings.tailscale_api_key") as mock_key:
        mock_key.get_secret_value.return_value = "tskey-api-test"
        with patch(
            "rp_server.routers.enroll.TailscaleAPIClient.create_authkey",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_response

            response = await client.post(
                "/v1/agent/reauth",
                json={
                    "host_id": host_id,
                    "machine_fingerprint": "test-fingerprint-reauth",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["tailscale_authkey"] == mock_response.key


@pytest.mark.asyncio
async def test_reauth_without_tailscale_api_key(client: AsyncClient, enrollment_token: str):
    """Test reauth when Tailscale API key is not configured."""
    # First enroll a host
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host-no-ts",
            "group": "test",
            "host_fingerprint": "test-fingerprint-no-ts",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "0.1.0",
        },
    )
    assert enroll_response.status_code == 201
    host_id = enroll_response.json()["host_id"]

    with patch("rp_server.config.settings.tailscale_api_key", None):
        response = await client.post(
            "/v1/agent/reauth",
            json={
                "host_id": host_id,
                "machine_fingerprint": "test-fingerprint-no-ts",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["tailscale_authkey"] is None


@pytest.mark.asyncio
async def test_reauth_tailscale_api_error(client: AsyncClient, enrollment_token: str):
    """Test reauth when Tailscale API fails."""
    from rp_server.integrations.tailscale_api import TailscaleAPIError

    # First enroll a host
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host-api-error",
            "group": "test",
            "host_fingerprint": "test-fingerprint-api-error",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "0.1.0",
        },
    )
    assert enroll_response.status_code == 201
    host_id = enroll_response.json()["host_id"]

    with patch("rp_server.config.settings.tailscale_api_key") as mock_key:
        mock_key.get_secret_value.return_value = "tskey-api-test"
        with patch(
            "rp_server.routers.enroll.TailscaleAPIClient.create_authkey",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.side_effect = TailscaleAPIError("API error")

            response = await client.post(
                "/v1/agent/reauth",
                json={
                    "host_id": host_id,
                    "machine_fingerprint": "test-fingerprint-api-error",
                },
            )

    # Unlike enrollment, reauth should fail if Tailscale API errors
    # (since reauth is specifically for Tailscale rejoin scenarios)
    assert response.status_code == 500
