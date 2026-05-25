"""Test install command with mock server."""

import json

import httpx
import pytest
from click.testing import CliRunner

from rp.cli import main


@pytest.fixture
def mock_enroll_server(mocker):
    """Mock httpx.Client to simulate enrollment server."""

    def mock_post(url, **kwargs):
        """Mock POST request."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "host_id": "mock-host-uuid-123",
            "agent_config": {
                "heartbeat_interval_s": 30,
            },
        }

        def raise_for_status():
            if mock_response.status_code != 200:
                raise httpx.HTTPStatusError("Error", request=None, response=mock_response)

        mock_response.raise_for_status = raise_for_status
        return mock_response

    mock_client = mocker.Mock()
    mock_client.post = mock_post
    mock_client.close = mocker.Mock()

    return mock_client


def test_install_with_mock_server(temp_config_dir, mock_enroll_server, mocker):
    """Test install command with mocked server."""
    # Mock httpx.Client
    mocker.patch("rp.commands.install.httpx.Client", return_value=mock_enroll_server)

    # Mock save_config to use temp dir
    mock_save = mocker.patch("rp.commands.install.save_config")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "install",
            "--token=test-jwt-token",
            "--server=http://localhost:8080",
            "--hostname=test-host",
            "--group=test",
        ],
    )

    # Check success
    assert result.exit_code == 0
    assert "Remote-Pulse installed" in result.output
    assert "test-host" in result.output
    assert "mock-host-uuid-123" in result.output

    # Verify save_config was called
    mock_save.assert_called_once()
    saved_config = mock_save.call_args[0][0]
    assert saved_config.host_id == "mock-host-uuid-123"
    assert saved_config.server_url == "http://localhost:8080"
    assert saved_config.heartbeat_interval_s == 30
