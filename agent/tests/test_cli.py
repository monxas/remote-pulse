"""Tests for CLI commands."""

from click.testing import CliRunner

from rp.cli import main
from rp.config import load_config


def test_version_command():
    """Test version command."""
    runner = CliRunner()
    result = runner.invoke(main, ["version"])

    assert result.exit_code == 0
    assert "remote-pulse agent version" in result.output
    assert "Python:" in result.output


def test_status_not_installed():
    """Test status command when not installed."""
    runner = CliRunner()
    result = runner.invoke(main, ["status"])

    # Should exit with error when not installed
    assert result.exit_code == 1
    assert "NOT INSTALLED" in result.output


def test_config_load(mock_config_file):
    """Test config loading."""
    config = load_config(mock_config_file)

    assert config.host_id == "test-host-123"
    assert config.server_url == "https://test.example.com"
    assert config.heartbeat_interval_s == 30
    assert config.group == "test"


def test_heartbeat_requires_config():
    """Test that heartbeat command requires config."""
    runner = CliRunner()
    result = runner.invoke(main, ["heartbeat", "--once"])

    assert result.exit_code == 1
    assert "not installed" in result.output.lower()
