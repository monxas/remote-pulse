"""Tests for heartbeat endpoint."""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.models import Host


@pytest.mark.asyncio
async def test_heartbeat_success(
    client: AsyncClient,
    test_db: AsyncSession,
    enrollment_token: str,
) -> None:
    """Test successful heartbeat submission."""
    # Enroll a host first
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host",
            "group": "test-group",
            "host_fingerprint": "abc123",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "0.1.0",
        },
    )
    assert enroll_response.status_code == 201
    host_id = enroll_response.json()["host_id"]

    # Send heartbeat
    response = await client.post(
        "/v1/heartbeat",
        json={
            "host_id": host_id,
            "cpu_pct": 45.2,
            "mem_pct": 62.8,
            "load_1m": 1.5,
            "uptime_s": 86400,
            "agent_version": "0.1.0",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "server_ts" in data

    # Verify host.last_seen_at was updated
    stmt = select(Host).where(Host.id == uuid.UUID(host_id))
    result = await test_db.execute(stmt)
    host = result.scalar_one()
    assert host.last_seen_at is not None


@pytest.mark.asyncio
async def test_heartbeat_unknown_host(client: AsyncClient) -> None:
    """Test heartbeat for non-existent host."""
    fake_host_id = str(uuid.uuid4())

    response = await client.post(
        "/v1/heartbeat",
        json={
            "host_id": fake_host_id,
            "cpu_pct": 50.0,
            "mem_pct": 60.0,
            "agent_version": "0.1.0",
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_heartbeat_validation(client: AsyncClient, enrollment_token: str) -> None:
    """Test heartbeat validation for out-of-range values."""
    enroll_response = await client.post(
        "/v1/enroll",
        json={
            "token": enrollment_token,
            "hostname": "test-host",
            "group": "test-group",
            "host_fingerprint": "abc123",
            "os": "linux",
            "arch": "x86_64",
            "agent_version": "0.1.0",
        },
    )
    host_id = enroll_response.json()["host_id"]

    # Invalid cpu_pct > 100
    response = await client.post(
        "/v1/heartbeat",
        json={
            "host_id": host_id,
            "cpu_pct": 150.0,
            "mem_pct": 60.0,
            "agent_version": "0.1.0",
        },
    )

    assert response.status_code == 422  # Validation error
