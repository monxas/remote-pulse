"""Tests for screen sharing capabilities (F6)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rp.screen import (
    HostResolver,
    ResolvedHost,
    RustDeskLauncher,
    SunshineLauncher,
    VNCLauncher,
)


@pytest.fixture
def mock_client():
    """Mock RPClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_host_response():
    """Mock server response for host query."""
    return [
        {
            "hostname": "pmx-50",
            "fqdn": "pmx-50.monxas.casa",
            "group": "prod",
            "capabilities": {
                "tailscale_ip": "100.64.0.50",
                "tailscale_node_id": "n123abc",
                "rustdesk_password": "test123",
                "tailscale_ssh_enabled": True,
            },
        },
        {
            "hostname": "carmelo",
            "group": "family",
            "capabilities": {
                "tailscale_ip": "100.64.0.100",
                "sunshine_enabled": True,
            },
        },
    ]


@pytest.mark.asyncio
async def test_host_resolver_success(mock_client, mock_host_response):
    """Test successful host resolution."""
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=mock_host_response)
    mock_client.get = AsyncMock(return_value=mock_response)

    resolver = HostResolver(mock_client)
    resolved = await resolver.resolve("pmx-50")

    assert resolved.hostname == "pmx-50"
    assert resolved.tailscale_ip == "100.64.0.50"
    assert resolved.magicdns_name == "pmx-50.monxas.ts.net"
    assert resolved.capabilities["rustdesk_password"] == "test123"
    assert resolved.group == "prod"


@pytest.mark.asyncio
async def test_host_resolver_not_found(mock_client):
    """Test host not found."""
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=[])
    mock_client.get = AsyncMock(return_value=mock_response)

    resolver = HostResolver(mock_client)

    with pytest.raises(ValueError, match="No host found matching"):
        await resolver.resolve("nonexistent")


@pytest.mark.asyncio
async def test_host_resolver_ambiguous(mock_client, mock_host_response):
    """Test ambiguous host match."""
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=mock_host_response)
    mock_client.get = AsyncMock(return_value=mock_response)

    resolver = HostResolver(mock_client)

    # "m" matches both "pmx-50" and "carmelo"
    with pytest.raises(ValueError, match="Ambiguous target"):
        await resolver.resolve("m")


@pytest.mark.asyncio
async def test_rustdesk_launcher_success():
    """Test RustDesk launcher with mock binary."""
    host = ResolvedHost(
        hostname="pmx-50",
        tailscale_ip="100.64.0.50",
        magicdns_name="pmx-50.monxas.ts.net",
        capabilities={"rustdesk_password": "test123"},
        group="prod",
    )

    launcher = RustDeskLauncher()

    with patch.object(
        launcher, "_find_rustdesk_binary", return_value="/usr/bin/rustdesk"
    ):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.wait.return_value = 0
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            exit_code = await launcher.launch(host)

            assert exit_code == 0
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert "/usr/bin/rustdesk" in args
            assert "--connect" in args
            assert "100.64.0.50" in args
            assert "--password" in args
            assert "test123" in args


@pytest.mark.asyncio
async def test_rustdesk_launcher_not_installed():
    """Test RustDesk launcher when binary not found."""
    host = ResolvedHost(
        hostname="pmx-50",
        tailscale_ip="100.64.0.50",
        magicdns_name="pmx-50.monxas.ts.net",
        capabilities={"rustdesk_password": "test123"},
        group="prod",
    )

    launcher = RustDeskLauncher()

    with patch.object(launcher, "_find_rustdesk_binary", return_value=None):
        with pytest.raises(FileNotFoundError, match="RustDesk not installed"):
            await launcher.launch(host)


@pytest.mark.asyncio
async def test_rustdesk_launcher_no_password():
    """Test RustDesk launcher when host has no password."""
    host = ResolvedHost(
        hostname="pmx-50",
        tailscale_ip="100.64.0.50",
        magicdns_name="pmx-50.monxas.ts.net",
        capabilities={},
        group="prod",
    )

    launcher = RustDeskLauncher()

    with patch.object(
        launcher, "_find_rustdesk_binary", return_value="/usr/bin/rustdesk"
    ):
        with pytest.raises(ValueError, match="no rustdesk_password capability"):
            await launcher.launch(host)


@pytest.mark.asyncio
async def test_sunshine_launcher_success():
    """Test Sunshine launcher with mock binary."""
    host = ResolvedHost(
        hostname="carmelo",
        tailscale_ip="100.64.0.100",
        magicdns_name="carmelo.monxas.ts.net",
        capabilities={"sunshine_enabled": True},
        group="family",
    )

    launcher = SunshineLauncher()

    with patch.object(
        launcher, "_find_moonlight_binary", return_value="/usr/bin/moonlight"
    ):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.wait.return_value = 0
            mock_proc.pid = 54321
            mock_popen.return_value = mock_proc

            exit_code = await launcher.launch(host)

            assert exit_code == 0
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert "/usr/bin/moonlight" in args
            assert "stream" in args
            assert "100.64.0.100" in args


@pytest.mark.asyncio
async def test_sunshine_launcher_not_enabled():
    """Test Sunshine launcher when not enabled on host."""
    host = ResolvedHost(
        hostname="pmx-50",
        tailscale_ip="100.64.0.50",
        magicdns_name="pmx-50.monxas.ts.net",
        capabilities={},
        group="prod",
    )

    launcher = SunshineLauncher()

    with pytest.raises(ValueError, match="does not have Sunshine enabled"):
        await launcher.launch(host)


@pytest.mark.asyncio
async def test_vnc_launcher_success():
    """Test VNC launcher with mock binary."""
    host = ResolvedHost(
        hostname="lxc-100",
        tailscale_ip="100.64.0.10",
        magicdns_name="lxc-100.monxas.ts.net",
        capabilities={"vnc_installed": True},
        group="prod",
    )

    launcher = VNCLauncher()

    with patch.object(launcher, "_find_vnc_viewer", return_value="/usr/bin/vncviewer"):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.wait.return_value = 0
            mock_popen.return_value = mock_proc

            exit_code = await launcher.launch(host)

            assert exit_code == 0
            mock_popen.assert_called_once()
