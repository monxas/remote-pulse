"""Tests for enrollment with Tailscale API integration."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from rp_server.integrations.tailscale_api import TailscaleAuthKeyResponse


@pytest.mark.asyncio
async def test_enroll_without_tailscale_api_key(client: AsyncClient, enrollment_token: str):
    """Test enrollment when Tailscale API key is not configured (degraded mode)."""
    with patch("rp_server.config.settings.tailscale_api_key", None):
        response = await client.post(
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

    assert response.status_code == 201
    data = response.json()
    assert data["agent_config"]["tailscale_authkey"] is None


@pytest.mark.asyncio
async def test_enroll_with_tailscale_api_key(client: AsyncClient, enrollment_token: str):
    """Test enrollment with Tailscale API key configured."""
    mock_response = TailscaleAuthKeyResponse(
        id="k123456",
        key="tskey-auth-test-xxxxxxxxxxxxxxxxxxxxxxxx",
        created="2026-05-25T12:00:00Z",
        expires="2026-05-26T12:00:00Z",
        revoked=False,
        capabilities={"devices": {"create": {"ephemeral": True}}},
        description="rp enroll test-host",
    )

    with patch("rp_server.config.settings.tailscale_api_key") as mock_key:
        mock_key.get_secret_value.return_value = "tskey-api-test"
        with patch(
            "rp_server.routers.enroll.TailscaleAPIClient.create_authkey",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_response

            response = await client.post(
                "/v1/enroll",
                json={
                    "token": enrollment_token,
                    "hostname": "test-host",
                    "group": "prod",
                    "host_fingerprint": "test-fingerprint-123",
                    "os": "linux",
                    "arch": "x86_64",
                    "distro": "debian-12",
                    "agent_version": "0.1.0",
                },
            )

    assert response.status_code == 201
    data = response.json()
    assert data["agent_config"]["tailscale_authkey"] == mock_response.key

    # Verify API client was called with correct parameters
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["ephemeral"] is True
    assert call_kwargs["reusable"] is False
    assert call_kwargs["preauthorized"] is True
    assert "tag:rp-agent-prod" in call_kwargs["tags"]


@pytest.mark.asyncio
async def test_enroll_with_tailscale_api_error(client: AsyncClient, enrollment_token: str):
    """Test enrollment continues in degraded mode when Tailscale API fails."""
    from rp_server.integrations.tailscale_api import TailscaleAPIError

    with patch("rp_server.config.settings.tailscale_api_key") as mock_key:
        mock_key.get_secret_value.return_value = "tskey-api-test"
        with patch(
            "rp_server.routers.enroll.TailscaleAPIClient.create_authkey",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.side_effect = TailscaleAPIError("API timeout")

            response = await client.post(
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

    # Enrollment should succeed even if Tailscale API fails
    assert response.status_code == 201
    data = response.json()
    assert data["agent_config"]["tailscale_authkey"] is None


@pytest.mark.asyncio
async def test_enroll_group_tag_mapping(client: AsyncClient, enrollment_token: str):
    """Test that group names are correctly mapped to Tailscale tags."""
    mock_response = TailscaleAuthKeyResponse(
        id="k123456",
        key="tskey-auth-test-xxxxxxxxxxxxxxxxxxxxxxxx",
        created="2026-05-25T12:00:00Z",
        expires="2026-05-26T12:00:00Z",
        revoked=False,
        capabilities={"devices": {"create": {"ephemeral": True}}},
    )

    with patch("rp_server.config.settings.tailscale_api_key") as mock_key:
        mock_key.get_secret_value.return_value = "tskey-api-test"
        with patch(
            "rp_server.routers.enroll.TailscaleAPIClient.create_authkey",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_response

            # Test family group
            response = await client.post(
                "/v1/enroll",
                json={
                    "token": enrollment_token,
                    "hostname": "test-host-family",
                    "group": "family",
                    "host_fingerprint": "test-fingerprint-family",
                    "os": "linux",
                    "arch": "x86_64",
                    "agent_version": "0.1.0",
                },
            )

    assert response.status_code == 201

    call_kwargs = mock_create.call_args.kwargs
    assert "tag:rp-agent-family" in call_kwargs["tags"]
