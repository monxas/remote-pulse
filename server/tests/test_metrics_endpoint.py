"""Tests for Prometheus /metrics endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.models import Enrollment, Heartbeat, Host
from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(client: AsyncClient):
    """Test /metrics endpoint returns 200 with Prometheus content type."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_output_contains_expected_metrics(client: AsyncClient):
    """Test /metrics output contains expected metric families."""
    response = await client.get("/metrics")
    content = response.text

    # Check for presence of key metrics
    assert "rp_host_up" in content
    assert "rp_host_cpu_pct" in content
    assert "rp_host_mem_pct" in content
    assert "rp_host_load_1m" in content
    assert "rp_host_uptime_seconds" in content
    assert "rp_host_last_seen_age_seconds" in content
    assert "rp_host_agent_version" in content
    assert "rp_enrollment_tokens_active" in content
    assert "rp_ssh_keys_total" in content
    assert "rp_enroll_total" in content
    assert "rp_heartbeat_total" in content


@pytest.mark.asyncio
async def test_metrics_after_enroll_and_heartbeat(
    client: AsyncClient, db_session: AsyncSession, enrollment_token: str
):
    """Test metrics counters increment after enrollment and heartbeat."""
    # Create enrollment record
    from rp_server.auth import decode_enrollment_token

    payload = decode_enrollment_token(enrollment_token)

    enrollment = Enrollment(
        token_jti=payload["jti"],
        issued_by="test-user",
        group_name="test-group",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        max_uses=5,
        used_count=0,
    )
    db_session.add(enrollment)
    await db_session.commit()

    # Enroll agent
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host-metrics",
            "os": "linux",
            "arch": "x64",
            "agent_version": "0.1.0",
            "host_fingerprint": "test-fingerprint-metrics",
        },
    )
    assert enroll_response.status_code == 201
    host_id = enroll_response.json()["host_id"]

    # Send heartbeat
    heartbeat_response = await client.post(
        "/v1/heartbeat",
        json={
            "host_id": host_id,
            "agent_ts": datetime.now(timezone.utc).isoformat(),
            "cpu_pct": 45.2,
            "mem_pct": 67.8,
            "load_1m": 1.23,
            "uptime_s": 123456,
            "agent_version": "0.1.0",
        },
    )
    assert heartbeat_response.status_code == 200

    # Check metrics
    metrics_response = await client.get("/metrics")
    content = metrics_response.text

    # Check enrollment counter incremented
    assert 'rp_enroll_total{group="test-group",result="success"}' in content

    # Check heartbeat counter incremented
    assert 'rp_heartbeat_total{group="test-group"}' in content

    # Check host gauges present with correct labels
    assert f'host_id="{host_id}"' in content
    assert 'hostname="test-host-metrics"' in content
    assert 'group="test-group"' in content


@pytest.mark.asyncio
async def test_metrics_multiple_hosts(client: AsyncClient, db_session: AsyncSession):
    """Test metrics correctly report multiple hosts with distinct labels."""
    now = datetime.now(timezone.utc)

    # Create two hosts
    host1 = Host(
        hostname="host1",
        os="linux",
        arch="x64",
        agent_version="0.1.0",
        group_name="group-a",
        last_seen_at=now - timedelta(seconds=30),
    )
    host2 = Host(
        hostname="host2",
        os="linux",
        arch="arm64",
        agent_version="0.1.1",
        group_name="group-b",
        last_seen_at=now - timedelta(seconds=200),  # >180s ago, should be down
    )

    db_session.add_all([host1, host2])
    await db_session.commit()
    await db_session.refresh(host1)
    await db_session.refresh(host2)

    # Add heartbeats
    hb1 = Heartbeat(
        host_id=host1.id,
        ts=now,
        cpu_pct=25.0,
        mem_pct=50.0,
        load_1m=0.5,
        uptime_s=10000,
        agent_version="0.1.0",
    )
    hb2 = Heartbeat(
        host_id=host2.id,
        ts=now - timedelta(seconds=200),
        cpu_pct=75.0,
        mem_pct=80.0,
        load_1m=2.5,
        uptime_s=20000,
        agent_version="0.1.1",
    )
    db_session.add_all([hb1, hb2])
    await db_session.commit()

    # Get metrics
    response = await client.get("/metrics")
    content = response.text

    # Check both hosts present
    assert 'hostname="host1"' in content
    assert 'hostname="host2"' in content

    # Check host1 is up (last_seen < 180s)
    assert f'rp_host_up{{group="group-a",host_id="{host1.id}",hostname="host1"}} 1.0' in content

    # Check host2 is down (last_seen > 180s)
    assert f'rp_host_up{{group="group-b",host_id="{host2.id}",hostname="host2"}} 0.0' in content

    # Check distinct metrics values
    assert "rp_host_cpu_pct" in content
    assert 'version="0.1.0"' in content
    assert 'version="0.1.1"' in content


@pytest.mark.asyncio
async def test_metrics_http_duration_histogram(client: AsyncClient):
    """Test HTTP request duration histogram is recorded."""
    # Make a few requests
    await client.get("/health")
    await client.get("/health")

    # Get metrics
    response = await client.get("/metrics")
    content = response.text

    # Check histogram present
    assert "rp_http_request_duration_seconds" in content
    assert "rp_http_request_duration_seconds_bucket" in content
    assert 'path="/health"' in content
    assert 'method="GET"' in content
    assert 'status="200"' in content
