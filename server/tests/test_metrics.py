"""Tests for metrics endpoints (sparkline data)."""

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.models import Heartbeat, Host


@pytest.fixture
async def host_with_metrics(db_session: AsyncSession) -> Host:
    """Create a test host with sinusoidal CPU metrics over 100 seconds."""
    host = Host(
        hostname="test-metrics-host",
        os="linux",
        arch="x86_64",
        agent_version="0.1.0",
        distro="debian-12",
    )
    db_session.add(host)
    await db_session.commit()
    await db_session.refresh(host)

    # Insert 100 heartbeats with timestamps spaced 1s apart
    # CPU values follow sine wave: 50 + 40*sin(x) to range [10, 90]
    # MEM values linear: 20 + x/2 to range [20, 70]
    now = datetime.now(timezone.utc)
    heartbeats = []

    for i in range(100):
        ts = now - timedelta(seconds=(100 - i))
        cpu_val = 50 + 40 * math.sin(i / 10)  # Sine wave
        mem_val = 20 + (i / 2)  # Linear increase
        load_val = 1.0 + (i / 50)  # Linear increase 1.0 -> 3.0

        heartbeat = Heartbeat(
            host_id=host.id,
            ts=ts,
            agent_ts=ts,
            cpu_pct=cpu_val,
            mem_pct=mem_val,
            load_1m=load_val,
            uptime_s=1000 + i,
            agent_version="0.1.0",
        )
        heartbeats.append(heartbeat)

    db_session.add_all(heartbeats)
    await db_session.commit()

    return host


@pytest.mark.asyncio
async def test_sparkline_1m_window(
    client: AsyncClient, host_with_metrics: Host, db_session: AsyncSession
) -> None:
    """Test sparkline returns data for 1m window with 1s buckets."""
    # Check if TimescaleDB is available
    try:
        result = await db_session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        )
        if result.scalar_one_or_none() is None:
            pytest.skip("TimescaleDB extension not installed")
    except Exception:
        pytest.skip("TimescaleDB extension not available")

    response = await client.get(
        f"/v1/metrics/{host_with_metrics.id}/sparkline",
        params={
            "series": ["cpu_pct", "mem_pct"],
            "window": "1m",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["host_id"] == str(host_with_metrics.id)
    assert data["window"] == "1m"
    assert data["bucket_seconds"] == 1
    assert len(data["series"]) == 2

    # Find CPU series
    cpu_series = next(s for s in data["series"] if s["metric"] == "cpu_pct")
    assert len(cpu_series["points"]) > 0  # Should have points in last minute

    # Verify points are tuples of [timestamp, value]
    for point in cpu_series["points"]:
        assert len(point) == 2
        assert isinstance(point[0], str)  # ISO timestamp
        assert isinstance(point[1], (int, float))


@pytest.mark.asyncio
async def test_sparkline_1h_window(
    client: AsyncClient, host_with_metrics: Host, db_session: AsyncSession
) -> None:
    """Test sparkline returns aggregated data for 1h window with 60s buckets."""
    # Check if TimescaleDB is available
    try:
        result = await db_session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        )
        if result.scalar_one_or_none() is None:
            pytest.skip("TimescaleDB extension not installed")
    except Exception:
        pytest.skip("TimescaleDB extension not available")

    response = await client.get(
        f"/v1/metrics/{host_with_metrics.id}/sparkline",
        params={
            "series": ["cpu_pct", "mem_pct", "load_1m"],
            "window": "1h",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["window"] == "1h"
    assert data["bucket_seconds"] == 60
    assert len(data["series"]) == 3

    # Verify all metrics returned
    metrics = {s["metric"] for s in data["series"]}
    assert metrics == {"cpu_pct", "mem_pct", "load_1m"}


@pytest.mark.asyncio
async def test_sparkline_missing_host(client: AsyncClient) -> None:
    """Test sparkline returns 404 for non-existent host."""
    fake_host_id = uuid4()
    response = await client.get(
        f"/v1/metrics/{fake_host_id}/sparkline",
        params={
            "series": ["cpu_pct"],
            "window": "5m",
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sparkline_invalid_window(client: AsyncClient, host_with_metrics: Host) -> None:
    """Test sparkline returns 400 for invalid window parameter."""
    response = await client.get(
        f"/v1/metrics/{host_with_metrics.id}/sparkline",
        params={
            "series": ["cpu_pct"],
            "window": "invalid",
        },
    )

    assert response.status_code == 400
    assert "Invalid window" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sparkline_default_params(client: AsyncClient, host_with_metrics: Host) -> None:
    """Test sparkline uses defaults when params not specified."""
    response = await client.get(f"/v1/metrics/{host_with_metrics.id}/sparkline")

    assert response.status_code == 200
    data = response.json()

    # Defaults: window=5m, series=[cpu_pct, mem_pct]
    assert data["window"] == "5m"
    assert data["bucket_seconds"] == 5
    assert len(data["series"]) == 2


@pytest.mark.asyncio
async def test_available_series(client: AsyncClient, host_with_metrics: Host) -> None:
    """Test /series endpoint returns list of available metrics."""
    response = await client.get(f"/v1/metrics/{host_with_metrics.id}/series")

    assert response.status_code == 200
    data = response.json()

    # F3: Should return hardcoded heartbeat metrics
    assert isinstance(data, list)
    assert "cpu_pct" in data
    assert "mem_pct" in data
    assert "load_1m" in data
    assert "uptime_s" in data


@pytest.mark.asyncio
async def test_available_series_missing_host(client: AsyncClient) -> None:
    """Test /series returns 404 for non-existent host."""
    fake_host_id = uuid4()
    response = await client.get(f"/v1/metrics/{fake_host_id}/series")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
