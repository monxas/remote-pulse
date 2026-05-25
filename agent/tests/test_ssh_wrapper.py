"""Tests for SSH wrapper with Tailscale SSH preferred (F6)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rp.ssh_wrapper import SSHWrapper
from rp.screen import ResolvedHost


@pytest.fixture
def mock_client():
    """Mock RPClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_resolved_host():
    """Mock resolved host."""
    return ResolvedHost(
        hostname="pmx-50",
        tailscale_ip="100.64.0.50",
        magicdns_name="pmx-50.monxas.ts.net",
        capabilities={"tailscale_ssh_enabled": True},
        group="prod",
    )


@pytest.mark.asyncio
async def test_ssh_wrapper_tailscale_preferred(mock_client, mock_resolved_host):
    """Test SSH wrapper prefers Tailscale SSH when available."""
    wrapper = SSHWrapper(mock_client)

    # Mock resolver
    with patch.object(wrapper.resolver, "resolve", return_value=mock_resolved_host):
        # Mock Tailscale SSH detection
        with patch.object(wrapper, "detect_tailscale_ssh", return_value=True):
            with patch("shutil.which", return_value="/usr/bin/tailscale"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)

                    exit_code = await wrapper.connect("pmx-50")

                    assert exit_code == 0
                    mock_run.assert_called_once()
                    args = mock_run.call_args[0][0]
                    assert "tailscale" in args[0]
                    assert "ssh" in args


@pytest.mark.asyncio
async def test_ssh_wrapper_classic_fallback(mock_client, mock_resolved_host):
    """Test SSH wrapper falls back to classic when Tailscale SSH fails."""
    wrapper = SSHWrapper(mock_client)

    # Disable Tailscale SSH on host
    mock_resolved_host.capabilities["tailscale_ssh_enabled"] = False

    with patch.object(wrapper.resolver, "resolve", return_value=mock_resolved_host):
        with patch.object(wrapper, "detect_tailscale_ssh", return_value=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                exit_code = await wrapper.connect("pmx-50")

                assert exit_code == 0
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                assert "ssh" in args[0]
                assert "100.64.0.50" in args


@pytest.mark.asyncio
async def test_ssh_wrapper_force_classic(mock_client, mock_resolved_host):
    """Test SSH wrapper with force_classic flag."""
    wrapper = SSHWrapper(mock_client)

    with patch.object(wrapper.resolver, "resolve", return_value=mock_resolved_host):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            exit_code = await wrapper.connect("pmx-50", force_classic=True)

            assert exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            # Should use classic SSH, not tailscale
            assert "ssh" in args[0]
            assert "tailscale" not in " ".join(args)


@pytest.mark.asyncio
async def test_ssh_wrapper_with_command(mock_client, mock_resolved_host):
    """Test SSH wrapper with remote command."""
    wrapper = SSHWrapper(mock_client)

    mock_resolved_host.capabilities["tailscale_ssh_enabled"] = False

    with patch.object(wrapper.resolver, "resolve", return_value=mock_resolved_host):
        with patch.object(wrapper, "detect_tailscale_ssh", return_value=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                exit_code = await wrapper.connect(
                    "pmx-50", command=["systemctl", "status", "caddy"]
                )

                assert exit_code == 0
                args = mock_run.call_args[0][0]
                assert "systemctl" in args
                assert "status" in args
                assert "caddy" in args


@pytest.mark.asyncio
async def test_ssh_wrapper_with_user(mock_client, mock_resolved_host):
    """Test SSH wrapper with custom user."""
    wrapper = SSHWrapper(mock_client)

    mock_resolved_host.capabilities["tailscale_ssh_enabled"] = False

    with patch.object(wrapper.resolver, "resolve", return_value=mock_resolved_host):
        with patch.object(wrapper, "detect_tailscale_ssh", return_value=False):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                exit_code = await wrapper.connect("pmx-50", user="ramon")

                assert exit_code == 0
                args = mock_run.call_args[0][0]
                assert "ramon@100.64.0.50" in args


def test_detect_tailscale_ssh_available():
    """Test Tailscale SSH detection when available."""
    wrapper = SSHWrapper(MagicMock())

    with patch("shutil.which", return_value="/usr/bin/tailscale"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = wrapper.detect_tailscale_ssh()

            assert result is True


def test_detect_tailscale_ssh_not_available():
    """Test Tailscale SSH detection when not available."""
    wrapper = SSHWrapper(MagicMock())

    with patch("shutil.which", return_value=None):
        result = wrapper.detect_tailscale_ssh()

        assert result is False


@pytest.mark.asyncio
async def test_is_target_ts_ssh_capable(mock_client, mock_resolved_host):
    """Test target Tailscale SSH capability check."""
    wrapper = SSHWrapper(mock_client)

    # Enabled
    result = await wrapper.is_target_ts_ssh_capable(mock_resolved_host)
    assert result is True

    # Disabled
    mock_resolved_host.capabilities["tailscale_ssh_enabled"] = False
    result = await wrapper.is_target_ts_ssh_capable(mock_resolved_host)
    assert result is False
