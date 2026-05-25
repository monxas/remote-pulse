"""Tests for canary deploy system."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from rp_server.models import Host, CanaryDeploy, Command


@pytest.fixture
async def test_hosts(db_session):
    """Create test hosts in prod group."""
    hosts = []
    for i in range(3):
        host = Host(
            hostname=f"prod-host-{i}",
            fqdn=f"prod-host-{i}.example.com",
            os="linux",
            arch="x86_64",
            distro="debian-12",
            agent_version="0.1.0",
            group_name="prod",
        )
        db_session.add(host)
        hosts.append(host)

    await db_session.commit()
    for host in hosts:
        await db_session.refresh(host)

    return hosts


@pytest.mark.asyncio
async def test_canary_upgrade_initiate(client: AsyncClient, test_hosts):
    """Test initiating canary upgrade."""
    payload = {
        "group": "prod",
        "target_version": "0.2.0",
        "observation_minutes": 10,
    }

    response = await client.post("/v1/admin/commands/canary-upgrade", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["target_version"] == "0.2.0"
    assert data["group_name"] == "prod"
    assert data["observation_minutes"] == 10
    assert data["state"] == "pending"
    assert "canary_id" in data
    assert "canary_hostname" in data
    assert data["canary_hostname"].startswith("prod-host-")


@pytest.mark.asyncio
async def test_canary_upgrade_specific_host(client: AsyncClient, test_hosts, db_session):
    """Test initiating canary upgrade with specific host."""
    target_host = test_hosts[1]

    payload = {
        "group": "prod",
        "target_version": "0.2.0",
        "canary_host_id": str(target_host.id),
        "observation_minutes": 5,
    }

    response = await client.post("/v1/admin/commands/canary-upgrade", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["canary_host_id"] == str(target_host.id)
    assert data["canary_hostname"] == target_host.hostname


@pytest.mark.asyncio
async def test_canary_upgrade_creates_command(client: AsyncClient, test_hosts, db_session):
    """Test that canary upgrade creates signed command."""
    payload = {
        "group": "prod",
        "target_version": "0.2.0",
        "observation_minutes": 10,
    }

    response = await client.post("/v1/admin/commands/canary-upgrade", json=payload)
    assert response.status_code == 201

    # Check that command was created
    stmt = select(Command).where(Command.command_type == "agent_upgrade")
    result = await db_session.execute(stmt)
    commands = result.scalars().all()

    assert len(commands) == 1
    cmd = commands[0]
    assert cmd.command_payload["target_version"] == "0.2.0"
    assert "canary_id" in cmd.command_payload
    assert cmd.server_signature is not None


@pytest.mark.asyncio
async def test_canary_upgrade_nonexistent_group(client: AsyncClient):
    """Test canary upgrade with nonexistent group."""
    payload = {
        "group": "nonexistent",
        "target_version": "0.2.0",
    }

    response = await client.post("/v1/admin/commands/canary-upgrade", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_canary_status(client: AsyncClient, test_hosts, db_session):
    """Test querying canary status."""
    # Create a canary deploy
    payload = {
        "group": "prod",
        "target_version": "0.2.0",
        "observation_minutes": 10,
    }

    create_response = await client.post("/v1/admin/commands/canary-upgrade", json=payload)
    assert create_response.status_code == 201

    canary_id = create_response.json()["canary_id"]

    # Query status
    response = await client.get(f"/v1/admin/commands/canary-status/{canary_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == canary_id
    assert data["group_name"] == "prod"
    assert data["target_version"] == "0.2.0"
    assert data["state"] == "pending"
    assert data["hosts_remaining"] >= 0
    assert data["hosts_upgraded"] >= 0


@pytest.mark.asyncio
async def test_canary_status_nonexistent(client: AsyncClient):
    """Test querying nonexistent canary."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/v1/admin/commands/canary-status/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_self_check_ok(client: AsyncClient, test_hosts, db_session):
    """Test agent self-check report (success)."""
    # Create canary deploy
    canary = CanaryDeploy(
        group_name="prod",
        target_version="0.2.0",
        canary_host_id=test_hosts[0].id,
        observation_minutes=10,
        initiated_by="admin",
        state="pending",
    )
    db_session.add(canary)
    await db_session.commit()
    await db_session.refresh(canary)

    # Send self-check report
    payload = {
        "host_id": str(test_hosts[0].id),
        "agent_version": "0.2.0",
        "upgrade_id": str(canary.id),
        "status": "ok",
        "errors": [],
    }

    response = await client.post("/v1/agent/self-check", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["acknowledged"] is True
    assert data["canary_state_updated"] is True

    # Verify canary state updated
    await db_session.refresh(canary)
    assert canary.state == "observing"
    assert canary.canary_health_check_at is not None


@pytest.mark.asyncio
async def test_self_check_failed(client: AsyncClient, test_hosts, db_session):
    """Test agent self-check report (failure)."""
    # Create canary deploy
    canary = CanaryDeploy(
        group_name="prod",
        target_version="0.2.0",
        canary_host_id=test_hosts[0].id,
        observation_minutes=10,
        initiated_by="admin",
        state="pending",
    )
    db_session.add(canary)
    await db_session.commit()
    await db_session.refresh(canary)

    # Send self-check report with failure
    payload = {
        "host_id": str(test_hosts[0].id),
        "agent_version": "0.2.0",
        "upgrade_id": str(canary.id),
        "status": "failed",
        "errors": ["version mismatch", "service not responding"],
    }

    response = await client.post("/v1/agent/self-check", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["acknowledged"] is True
    assert data["canary_state_updated"] is True

    # Verify canary state updated to failed
    await db_session.refresh(canary)
    assert canary.state == "failed_rollback"
    assert "self_check_failed" in canary.failed_reason
    assert canary.completed_at is not None


@pytest.mark.asyncio
async def test_version_handshake(client: AsyncClient, test_hosts):
    """Test version handshake from agent."""
    payload = {
        "host_id": str(test_hosts[0].id),
        "agent_version": "0.2.0",
        "api_compat_min": "1.0.0",
        "api_compat_max": "1.0.0",
    }

    response = await client.post("/v1/agent/version-handshake", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_report_rollback(client: AsyncClient, test_hosts):
    """Test rollback report from agent."""
    payload = {
        "host_id": str(test_hosts[0].id),
        "from_version": "0.2.0",
        "to_version": "0.1.0",
        "reason": "self_check_timeout",
    }

    response = await client.post("/v1/agent/rollback", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
