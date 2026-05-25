"""Pytest configuration and fixtures."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_config_dir():
    """Create temporary directory for config files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config_file(temp_config_dir):
    """Create mock config file."""
    config_path = temp_config_dir / "config.toml"
    config_path.write_text(
        """
host_id = "test-host-123"
server_url = "https://test.example.com"
heartbeat_interval_s = 30
group = "test"
"""
    )
    return config_path
