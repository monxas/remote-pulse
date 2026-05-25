"""Tests for TUI dashboard."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from textual.widgets import DataTable

from textual.widgets import Static

from rp.dash.app import RemotePulseApp
from rp.dash.widgets import HostDetail, HostList, SparklineWidget


@pytest.mark.asyncio
async def test_app_loads_without_crash():
    """Test that the app can be instantiated and mounted in headless mode."""
    # Mock API client to avoid network calls
    with patch("rp.dash.app.AsyncAPIClient") as mock_api_client_class:
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.list_hosts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_api_client_class.return_value = mock_client

        app = RemotePulseApp(server_url="http://localhost:8080")

        async with app.run_test() as pilot:
            # Wait a bit for mount
            await pilot.pause()

            # Check that main widgets are present
            assert app.query_one("#host-list", HostList)
            assert app.query_one("#host-detail", HostDetail)
            assert app.query_one("#footer-status")


@pytest.mark.asyncio
async def test_host_list_renders_mock_data():
    """Test that HostList widget can render mock host data."""
    with patch("rp.dash.app.AsyncAPIClient") as mock_api_client_class:
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.list_hosts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_api_client_class.return_value = mock_client

        app = RemotePulseApp(server_url="http://localhost:8080")

        async with app.run_test() as pilot:
            await pilot.pause()

            host_list = app.query_one("#host-list", HostList)

            # Mock host data
            mock_hosts = [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "hostname": "test-host-1",
                    "os": "linux",
                    "arch": "x86_64",
                    "agent_version": "0.1.0",
                    "group_name": "prod",
                    "enrolled_at": "2025-05-25T10:00:00Z",
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "hostname": "test-host-2",
                    "os": "linux",
                    "arch": "arm64",
                    "agent_version": "0.1.0",
                    "group_name": "dev",
                    "enrolled_at": "2025-05-25T09:00:00Z",
                    "last_seen_at": "2025-05-25T09:30:00Z",  # Old timestamp
                },
            ]

            host_list.update_hosts(mock_hosts)
            await pilot.pause()

            # Check that table has rows
            table = host_list.query_one(DataTable)
            assert table.row_count == 2


@pytest.mark.asyncio
async def test_sparkline_widget_accepts_data():
    """Test that SparklineWidget can accept and display data points."""
    with patch("rp.dash.app.AsyncAPIClient") as mock_api_client_class:
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.list_hosts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_api_client_class.return_value = mock_client

        app = RemotePulseApp(server_url="http://localhost:8080")

        async with app.run_test() as pilot:
            await pilot.pause()

            # Get a sparkline widget
            sparkline = app.query_one("#spark-cpu", SparklineWidget)

            # Mock data points
            now = datetime.now(timezone.utc)
            points = [
                (now, 10.0),
                (now, 20.0),
                (now, 30.0),
                (now, 25.0),
                (now, 15.0),
            ]

            # Should not crash
            sparkline.update_data(points)
            await pilot.pause()

            # Check that current value is set
            assert sparkline._current_value == 15.0


@pytest.mark.asyncio
async def test_host_detail_updates():
    """Test that HostDetail widget can be updated with host info."""
    with patch("rp.dash.app.AsyncAPIClient") as mock_api_client_class:
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.list_hosts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_api_client_class.return_value = mock_client

        app = RemotePulseApp(server_url="http://localhost:8080")

        async with app.run_test() as pilot:
            await pilot.pause()

            host_detail = app.query_one("#host-detail", HostDetail)

            # Mock host detail
            mock_detail = {
                "id": "11111111-1111-1111-1111-111111111111",
                "hostname": "test-host",
                "group_name": "prod",
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "recent_heartbeats": [],
            }

            host_detail.update_host_info(
                "11111111-1111-1111-1111-111111111111", mock_detail
            )
            await pilot.pause()

            # Check that hostname is displayed
            name_widget = host_detail.query_one("#host-name", Static)
            assert "test-host" in str(name_widget.render())


@pytest.mark.asyncio
async def test_keybindings_registered():
    """Test that app bindings are registered."""
    app = RemotePulseApp(server_url="http://localhost:8080")

    # Check that key bindings are defined
    binding_keys = [b.key for b in app.BINDINGS]
    assert "q" in binding_keys
    assert "r" in binding_keys
    assert "question_mark" in binding_keys
    assert "w" in binding_keys


@pytest.mark.asyncio
async def test_sparkline_clear():
    """Test that sparkline clear works."""
    with patch("rp.dash.app.AsyncAPIClient") as mock_api_client_class:
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.list_hosts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_api_client_class.return_value = mock_client

        app = RemotePulseApp(server_url="http://localhost:8080")

        async with app.run_test() as pilot:
            await pilot.pause()

            sparkline = app.query_one("#spark-mem", SparklineWidget)

            # Add data
            now = datetime.now(timezone.utc)
            points = [(now, 50.0), (now, 60.0)]
            sparkline.update_data(points)
            await pilot.pause()
            assert sparkline._current_value == 60.0

            # Clear
            sparkline.clear()
            await pilot.pause()
            assert sparkline._current_value is None
