"""Tests for agent-side API compatibility handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from rp.compat import APICompatHandler, IncompatibleVersionError


class TestAPICompatHandler:
    """Test agent compatibility handler."""

    @pytest.fixture
    def handler(self):
        return APICompatHandler("https://test-server.example.com")

    def test_add_version_headers(self, handler):
        """Test version headers are added correctly."""
        headers = {"User-Agent": "test"}
        result = handler.add_version_headers(headers)

        assert "Sec-RP-Agent-Version" in result
        assert "Sec-RP-Min-Server" in result
        assert "Sec-RP-Features" in result
        assert result["Sec-RP-Agent-Version"] == "0.1.0"

    def test_is_version_compatible(self, handler):
        """Test semver comparison."""
        assert handler._is_version_compatible("1.0.0", "0.1.0")
        assert handler._is_version_compatible("0.5.0", "0.5.0")
        assert not handler._is_version_compatible("0.1.0", "1.0.0")

    def test_is_version_deprecated_wildcard(self, handler):
        """Test wildcard deprecation pattern."""
        assert handler._is_version_deprecated("0.0.5", ["0.0.x"])
        assert handler._is_version_deprecated("0.0.999", ["0.0.x"])
        assert not handler._is_version_deprecated("0.1.0", ["0.0.x"])

    def test_is_version_deprecated_exact(self, handler):
        """Test exact deprecation match."""
        assert handler._is_version_deprecated("1.5.0", ["1.5.0"])
        assert not handler._is_version_deprecated("1.5.1", ["1.5.0"])

    @pytest.mark.asyncio
    async def test_check_handshake_success(self, handler, monkeypatch):
        """Test successful handshake."""
        # Mock httpx.AsyncClient
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "server_version": "1.0.0",
            "api_version": "v1",
            "min_agent_version": "0.1.0",
            "deprecated_agent_versions": ["0.0.x"],
            "features": ["heartbeat", "enroll"],
            "tailscale_ssh_supported": True,
            "rustdesk_direct_ip_supported": True,
            "sunshine_supported": False,
            "max_metrics_window": "1y",
            "metrics_retention_policy": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # Monkeypatch httpx.AsyncClient
        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        server_info = await handler.check_handshake()

        assert server_info.server_version == "1.0.0"
        assert "heartbeat" in server_info.features
        assert server_info.tailscale_ssh_supported is True

    @pytest.mark.asyncio
    async def test_check_handshake_agent_too_old(self, handler, monkeypatch):
        """Test handshake with agent below server minimum."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "server_version": "2.0.0",
            "api_version": "v2",
            "min_agent_version": "2.0.0",  # Agent 0.1.0 is too old
            "deprecated_agent_versions": [],
            "features": [],
            "tailscale_ssh_supported": True,
            "rustdesk_direct_ip_supported": True,
            "sunshine_supported": False,
            "max_metrics_window": "1y",
            "metrics_retention_policy": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        with pytest.raises(IncompatibleVersionError, match="Agent version"):
            await handler.check_handshake()

    @pytest.mark.asyncio
    async def test_check_handshake_server_too_old(self, handler, monkeypatch):
        """Test handshake with server below agent minimum."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "server_version": "0.0.5",  # Too old
            "api_version": "v0",
            "min_agent_version": "0.0.1",
            "deprecated_agent_versions": [],
            "features": [],
            "tailscale_ssh_supported": False,
            "rustdesk_direct_ip_supported": False,
            "sunshine_supported": False,
            "max_metrics_window": "30d",
            "metrics_retention_policy": {},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        with pytest.raises(IncompatibleVersionError, match="Server version"):
            await handler.check_handshake()

    def test_handle_compat_response_deprecated(self, handler):
        """Test handling deprecated agent response."""
        mock_response = MagicMock()
        mock_response.headers = {
            "Sec-RP-Deprecated": "true",
            "Sec-RP-Deprecated-Reason": "Please upgrade",
            "Sec-RP-Server-Version": "1.0.0",
        }

        # Should not raise, just log warning
        handler.handle_compat_response(mock_response)

    def test_handle_compat_response_ok(self, handler):
        """Test handling normal response."""
        mock_response = MagicMock()
        mock_response.headers = {
            "Sec-RP-Deprecated": "false",
            "Sec-RP-Server-Version": "1.0.0",
        }

        handler.handle_compat_response(mock_response)
