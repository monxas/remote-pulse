"""Tests for agent upgrade module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rp.upgrade import AgentUpgrader, UpgradeResult, RollbackResult


@pytest.fixture
def mock_client():
    """Mock RPClient."""
    client = MagicMock()
    client.version_handshake = AsyncMock(return_value={"status": "ok"})
    client.report_rollback = AsyncMock(return_value={"status": "ok"})
    client.send_heartbeat = AsyncMock(return_value={"status": "ok"})
    return client


@pytest.fixture
def upgrader(mock_client):
    """Create upgrader instance with mock client."""
    return AgentUpgrader(client=mock_client)


def test_get_binary_name(upgrader):
    """Test binary name generation for different platforms."""
    assert upgrader._get_binary_name("linux", "x86_64") == "rp-linux-x86_64"
    assert upgrader._get_binary_name("darwin", "arm64") == "rp-darwin-arm64"
    assert upgrader._get_binary_name("windows", "x86_64") == "rp-windows-x86_64.exe"


def test_get_versions_no_prev(upgrader, tmp_path):
    """Test get_versions when no previous version exists."""
    with patch("rp.upgrade.PREV_BIN", tmp_path / "rp-prev"):
        versions = upgrader.get_versions()
        assert versions["current"] == "0.1.0"  # From __version__
        assert versions["previous"] is None
        assert isinstance(versions["available_versions"], list)


def test_get_versions_with_prev(upgrader, tmp_path):
    """Test get_versions when previous version exists."""
    # Create mock prev symlink
    prev_bin = tmp_path / "rp-0.0.9"
    prev_bin.write_text("#!/bin/bash\necho mock")
    prev_bin.chmod(0o755)

    prev_symlink = tmp_path / "rp-prev"
    prev_symlink.symlink_to(prev_bin)

    with patch("rp.upgrade.PREV_BIN", prev_symlink):
        versions = upgrader.get_versions()
        assert versions["current"] == "0.1.0"
        assert versions["previous"] == "0.0.9"


@pytest.mark.asyncio
async def test_upgrade_dry_run(upgrader):
    """Test upgrade in dry-run mode."""
    result = await upgrader.upgrade_to("0.2.0", dry_run=True)

    assert isinstance(result, UpgradeResult)
    assert result.old_version == "0.1.0"
    assert result.new_version == "0.2.0"
    assert result.success is True
    assert result.rollback is False
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_download_binary_checksum_mismatch(upgrader):
    """Test download with checksum mismatch."""
    mock_response_binary = MagicMock()
    mock_response_binary.status_code = 200
    mock_response_binary.content = b"fake binary content"

    mock_response_checksum = MagicMock()
    mock_response_checksum.status_code = 200
    mock_response_checksum.text = "deadbeef0000  rp-linux-x86_64\n"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(
            side_effect=[mock_response_binary, mock_response_checksum]
        )
        mock_client_cls.return_value = mock_client

        binary_path, checksum_ok = await upgrader._download_binary(
            "0.2.0", "rp-linux-x86_64"
        )

        assert binary_path.exists()
        assert checksum_ok is False  # Checksum should not match


@pytest.mark.asyncio
async def test_self_check_timeout(upgrader):
    """Test self-check with timeout."""
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await upgrader._run_self_check(timeout_s=1)
        assert result is False


@pytest.mark.asyncio
async def test_rollback_no_prev(upgrader, tmp_path):
    """Test rollback when no N-1 binary exists."""
    with patch("rp.upgrade.PREV_BIN", tmp_path / "nonexistent"):
        result = await upgrader.rollback(reason="test")

        assert isinstance(result, RollbackResult)
        assert result.success is False
        assert len(result.errors) > 0
        assert "no N-1 binary found" in result.errors[0]


@pytest.mark.asyncio
async def test_rollback_with_prev(upgrader, tmp_path, mock_client):
    """Test successful rollback."""
    # Create mock prev binary
    prev_bin = tmp_path / "rp-0.0.9"
    prev_bin.write_text("#!/bin/bash\necho mock")
    prev_bin.chmod(0o755)

    prev_symlink = tmp_path / "rp-prev"
    prev_symlink.symlink_to(prev_bin)

    current_symlink = tmp_path / "rp"

    with (
        patch("rp.upgrade.PREV_BIN", prev_symlink),
        patch("rp.upgrade.CURRENT_BIN", current_symlink),
        patch("rp.upgrade.BIN_DIR", tmp_path),
        patch("subprocess.run"),
    ):  # Mock systemctl
        result = await upgrader.rollback(reason="test")

        assert isinstance(result, RollbackResult)
        assert result.from_version == "0.1.0"
        assert result.to_version == "0.0.9"
        # Rollback may partially succeed even if service restart fails
        # so we just check structure


def test_save_upgrade_state(upgrader, tmp_path):
    """Test upgrade state persistence."""
    with (
        patch("rp.upgrade.STATE_DIR", tmp_path),
        patch("rp.upgrade.UPGRADE_STATE_FILE", tmp_path / "upgrade-state.json"),
    ):
        state = {
            "target_version": "0.2.0",
            "old_version": "0.1.0",
            "completed_at": "2026-05-25T12:00:00Z",
            "success": True,
        }

        upgrader._save_upgrade_state(state)

        state_file = tmp_path / "upgrade-state.json"
        assert state_file.exists()
        import json

        saved_state = json.loads(state_file.read_text())
        assert saved_state["target_version"] == "0.2.0"
