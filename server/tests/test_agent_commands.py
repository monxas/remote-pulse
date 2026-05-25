"""Tests for the Phase 2.5 agent execution loop endpoints.

Covers:
  * GET  /v1/agent/commands/pending  — filtering, claim stamp, freshness window.
  * POST /v1/agent/commands/{id}/result — success, idempotency, host_id mismatch.
  * SSE event fan-out on result submission.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.events import event_bus
from rp_server.models import Command, Host


# ---- Local fixtures (this file owns its setup, no reliance on broken
# ``db_session`` alias from test_approvals.py) -------------------------------


@pytest.fixture
async def host_a(test_db: AsyncSession) -> Host:
    host = Host(
        hostname="agent-a",
        os="linux",
        arch="x86_64",
        agent_version="1.0.0",
        group_name="default",
    )
    test_db.add(host)
    await test_db.commit()
    await test_db.refresh(host)
    return host


@pytest.fixture
async def host_b(test_db: AsyncSession) -> Host:
    host = Host(
        hostname="agent-b",
        os="linux",
        arch="x86_64",
        agent_version="1.0.0",
        group_name="default",
    )
    test_db.add(host)
    await test_db.commit()
    await test_db.refresh(host)
    return host


async def _make_command(
    db: AsyncSession,
    *,
    host: Host,
    human_approved: bool = True,
    approval_token: uuid.UUID | None = None,
    approval_requested_at: datetime | None = None,
    completed_at: datetime | None = None,
    rejected_reason: str | None = None,
    issued_at: datetime | None = None,
    command_type: str = "shell",
    payload: dict | None = None,
) -> Command:
    cmd = Command(
        host_id=host.id,
        issued_by="pytest@example",
        command_type=command_type,
        command_payload=payload or {"cmd": "echo hello"},
        server_signature="sig-stub",
        human_approved=human_approved,
        approval_token=approval_token,
        approval_requested_at=approval_requested_at,
        completed_at=completed_at,
        rejected_reason=rejected_reason,
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)

    # Backdate issued_at if requested (SQLAlchemy sets it on insert via
    # Python default → we have to UPDATE after the fact).
    if issued_at is not None:
        from sqlalchemy import update as _update

        await db.execute(_update(Command).where(Command.id == cmd.id).values(issued_at=issued_at))
        await db.commit()
        await db.refresh(cmd)
    return cmd


# ---- GET /v1/agent/commands/pending ---------------------------------------


async def test_pending_returns_approved_for_target_host(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    resp = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["commands"]) == 1
    item = body["commands"][0]
    assert item["id"] == str(cmd.id)
    assert item["command_type"] == "shell"
    assert item["command_payload"] == {"cmd": "echo hello"}
    assert "server_signature" in item
    assert "issued_at" in item
    assert "issued_by" in item
    assert "expires_at" in item


async def test_pending_excludes_other_hosts(
    client: AsyncClient, test_db: AsyncSession, host_a: Host, host_b: Host
) -> None:
    await _make_command(test_db, host=host_b, human_approved=True)

    resp = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    assert resp.status_code == 200
    assert resp.json()["commands"] == []


async def test_pending_excludes_unapproved_with_token(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    # Token attached + not yet approved → blocked.
    await _make_command(
        test_db,
        host=host_a,
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=datetime.now(timezone.utc),
    )

    resp = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    assert resp.status_code == 200
    assert resp.json()["commands"] == []


async def test_pending_includes_plain_command_without_approval_flow(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    # No approval_token, no approval_requested_at, human_approved=False:
    # this is a low-risk command that didn't trigger the approval flow at
    # issue time. Should be eligible for execution.
    await _make_command(test_db, host=host_a, human_approved=False)

    resp = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    assert resp.status_code == 200
    assert len(resp.json()["commands"]) == 1


async def test_pending_excludes_completed(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    await _make_command(
        test_db, host=host_a, human_approved=True, completed_at=datetime.now(timezone.utc)
    )

    resp = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    assert resp.status_code == 200
    assert resp.json()["commands"] == []


async def test_pending_excludes_stale(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    await _make_command(test_db, host=host_a, human_approved=True, issued_at=stale)

    resp = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    assert resp.status_code == 200
    assert resp.json()["commands"] == []


async def test_pending_stamps_agent_node_id(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    cmd = await _make_command(test_db, host=host_a, human_approved=True)
    assert cmd.agent_node_id is None

    await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")

    refreshed = (
        await test_db.execute(select(Command).where(Command.id == cmd.id))
    ).scalar_one()
    assert refreshed.agent_node_id == str(host_a.id)


async def test_pending_idempotent_within_window(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    await _make_command(test_db, host=host_a, human_approved=True)

    r1 = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")
    r2 = await client.get(f"/v1/agent/commands/pending?host_id={host_a.id}")

    assert r1.status_code == 200 and r2.status_code == 200
    ids1 = [c["id"] for c in r1.json()["commands"]]
    ids2 = [c["id"] for c in r2.json()["commands"]]
    assert ids1 == ids2


async def test_pending_unknown_host_404(client: AsyncClient) -> None:
    resp = await client.get(f"/v1/agent/commands/pending?host_id={uuid.uuid4()}")
    assert resp.status_code == 404


# ---- POST /v1/agent/commands/{id}/result ----------------------------------


def _result_body(**overrides) -> dict:
    body = {
        "exit_code": 0,
        "stdout": "hello\n",
        "stderr": "",
        "duration_ms": 12,
        "agent_ts": datetime.now(timezone.utc).isoformat(),
    }
    body.update(overrides)
    return body


async def test_result_records_outcome(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    resp = await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_a.id}",
        json=_result_body(exit_code=0, stdout="ok\n"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ack"] is True

    refreshed = (
        await test_db.execute(select(Command).where(Command.id == cmd.id))
    ).scalar_one()
    assert refreshed.exit_code == 0
    assert refreshed.stdout == "ok\n"
    assert refreshed.completed_at is not None
    assert refreshed.duration_ms == 12
    assert refreshed.agent_node_id == str(host_a.id)


async def test_result_double_submit_returns_409(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    r1 = await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_a.id}",
        json=_result_body(),
    )
    assert r1.status_code == 200

    r2 = await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_a.id}",
        json=_result_body(),
    )
    assert r2.status_code == 409


async def test_result_mismatched_host_returns_400(
    client: AsyncClient, test_db: AsyncSession, host_a: Host, host_b: Host
) -> None:
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    resp = await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_b.id}",
        json=_result_body(),
    )
    assert resp.status_code == 400


async def test_result_unknown_command_returns_404(
    client: AsyncClient, host_a: Host
) -> None:
    resp = await client.post(
        f"/v1/agent/commands/{uuid.uuid4()}/result?host_id={host_a.id}",
        json=_result_body(),
    )
    assert resp.status_code == 404


async def test_result_fires_status_change_event(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    # Subscribe and collect events in the background.
    received: list[tuple[str, dict]] = []

    async def _collect() -> None:
        async for event_type, payload in event_bus.subscribe():
            received.append((event_type, payload))
            return  # one event is enough

    collector = asyncio.create_task(_collect())
    # Yield once so the subscriber registers before we publish.
    await asyncio.sleep(0)

    resp = await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_a.id}",
        json=_result_body(exit_code=0),
    )
    assert resp.status_code == 200

    try:
        await asyncio.wait_for(collector, timeout=1.0)
    except asyncio.TimeoutError:
        collector.cancel()
        pytest.fail("expected command.status_change event was not published")

    assert len(received) == 1
    event_type, payload = received[0]
    assert event_type == "command.status_change"
    assert payload["command_id"] == str(cmd.id)
    assert payload["host_id"] == str(host_a.id)
    assert payload["status"] == "succeeded"
    assert payload["exit_code"] == 0


async def test_result_status_mapping_failed(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    """exit_code != 0 maps to 'failed'."""
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    received: list[tuple[str, dict]] = []

    async def _collect() -> None:
        async for event_type, payload in event_bus.subscribe():
            received.append((event_type, payload))
            return

    collector = asyncio.create_task(_collect())
    await asyncio.sleep(0)

    await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_a.id}",
        json=_result_body(exit_code=1, stderr="boom"),
    )

    await asyncio.wait_for(collector, timeout=1.0)
    assert received[0][1]["status"] == "failed"


async def test_result_status_mapping_timeout(
    client: AsyncClient, test_db: AsyncSession, host_a: Host
) -> None:
    """exit_code=None with rejected_reason='timeout' maps to 'timeout'."""
    cmd = await _make_command(test_db, host=host_a, human_approved=True)

    received: list[tuple[str, dict]] = []

    async def _collect() -> None:
        async for event_type, payload in event_bus.subscribe():
            received.append((event_type, payload))
            return

    collector = asyncio.create_task(_collect())
    await asyncio.sleep(0)

    await client.post(
        f"/v1/agent/commands/{cmd.id}/result?host_id={host_a.id}",
        json=_result_body(exit_code=None, rejected_reason="timeout after 5s"),
    )

    await asyncio.wait_for(collector, timeout=1.0)
    assert received[0][1]["status"] == "timeout"
