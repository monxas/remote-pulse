"""Unit tests for Tailscale API client (no DB required)."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rp_server.integrations.tailscale_api import (
    TailscaleAPIClient,
    TailscaleAPIError,
    TailscaleAuthenticationError,
    TailscaleAuthKeyResponse,
    TailscalePermissionError,
    TailscaleValidationError,
)


@pytest.mark.asyncio
async def test_create_authkey_success():
    """Test successful auth key creation."""
    client = TailscaleAPIClient(api_key="tskey-api-test", tailnet="test-tailnet")

    mock_response_data = {
        "id": "k123456",
        "key": "tskey-auth-xxxxxxxxxxxxxxxxxxxxxxxx",
        "created": "2026-05-25T12:00:00Z",
        "expires": "2026-05-26T12:00:00Z",
        "revoked": False,
        "capabilities": {"devices": {"create": {"ephemeral": True}}},
        "description": "test key",
    }

    with patch("httpx.AsyncClient.__aenter__") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: mock_response_data
        mock_response.raise_for_status = lambda: None

        mock_post = AsyncMock(return_value=mock_response)
        mock_client.return_value.post = mock_post

        result = await client.create_authkey(
            tags=["tag:test"],
            description="test key",
        )

        assert result.key == "tskey-auth-xxxxxxxxxxxxxxxxxxxxxxxx"
        assert result.id == "k123456"
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_create_authkey_401_authentication_error():
    """Test 401 authentication error."""
    client = TailscaleAPIClient(api_key="invalid-key")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        with pytest.raises(TailscaleAuthenticationError):
            await client.create_authkey(tags=["tag:test"])


@pytest.mark.asyncio
async def test_create_authkey_403_permission_error():
    """Test 403 permission error."""
    client = TailscaleAPIClient(api_key="tskey-api-test")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_post.return_value = mock_response

        with pytest.raises(TailscalePermissionError):
            await client.create_authkey(tags=["tag:test"])


@pytest.mark.asyncio
async def test_create_authkey_422_validation_error():
    """Test 422 validation error."""
    client = TailscaleAPIClient(api_key="tskey-api-test")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 422
        mock_response.text = "Invalid payload"
        mock_post.return_value = mock_response

        with pytest.raises(TailscaleValidationError):
            await client.create_authkey(tags=["tag:test"])


@pytest.mark.asyncio
async def test_create_authkey_timeout_retry():
    """Test timeout with retry mechanism."""
    client = TailscaleAPIClient(api_key="tskey-api-test", max_retries=2)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")

        with pytest.raises(TailscaleAPIError, match="timeout"):
            await client.create_authkey(tags=["tag:test"])

        assert mock_post.call_count == 2  # max_retries


@pytest.mark.asyncio
async def test_create_authkey_500_retry():
    """Test 500 error with retry mechanism."""
    client = TailscaleAPIClient(api_key="tskey-api-test", max_retries=3)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        with pytest.raises(TailscaleAPIError, match="server error"):
            await client.create_authkey(tags=["tag:test"])

        assert mock_post.call_count == 3  # max_retries
