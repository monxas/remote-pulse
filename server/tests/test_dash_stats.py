"""Tests for the /v1/dash/stats aggregated KPI endpoint (ADR-0009).

We exercise the JSON shape, range validation, command/audit roll-ups,
per-host uptime calculation, and ACL scoping for non-admin viewers.

The SQLite test fixture lacks TimescaleDB's ``time_bucket()``, so the
endpoint's dialect detection takes the SQLite branch (``date()`` /
``strftime``). The Postgres path is exercised in the staging environment
and via the production smoke run; covering it from CI would need a
testcontainer which is beyond this slice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import AuditEvent, Command, Heartbeat, Host, User


# --------------------------------------------------------------------------- #
# Auth + DB helpers (mirror test_dash_api.py)
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    async def _fake_current_user() -> User:
        return user

    app.dependency_overrides[current_user] = _fake_current_user


def _clear_user_override() -> None:
    app.dependency_overrides.pop(current_user, None)


async def _make_admin(db: AsyncSession) -> User:
    user = User(
        pocketid_sub="admin-stats",
        email="admin@stats.local",
        name="Admin",
        role="admin",
        accessible_groups=[],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_viewer(db: AsyncSession, groups: list[str]) -> User:
    user = User(
        pocketid_sub=f"viewer-{uuid.uuid4().hex[:8]}",
        email=f"viewer-{uuid.uuid4().hex[:8]}@stats.local",
        name="Viewer",
        role="viewer",
        accessible_groups=groups,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_host(
    db: AsyncSession,
    *,
    hostname: str,
    group: str | None = "prod",
    last_seen_s_ago: int | None = 10,
) -> Host:
    now = datetime.now(timezone.utc)
    last_seen = (
        now - timedelta(seconds=last_seen_s_ago) if last_seen_s_ago is not None else None
    )
    host = Host(
        hostname=hostname,
        os="linux",
        arch="x86_64",
        agent_version="1.0.0",
        group_name=group,
        last_seen_at=last_seen,
    )
    db.add(host)
    await db.commit()
    await db.refresh(host)
    return host


async def _make_command(
    db: AsyncSession,
    *,
    host_id: uuid.UUID,
    command_type: str = "shell",
    exit_code: int | None = 0,
    issued_at: datetime | None = None,
    completed: bool = True,
) -> Command:
    if issued_at is None:
        issued_at = datetime.now(timezone.utc) - timedelta(hours=1)
    cmd = Command(
        host_id=host_id,
        issued_by="admin@stats.local",
        command_type=command_type,
        command_payload={"args": ["echo", "hi"]},
        issued_at=issued_at,
        completed_at=issued_at + timedelta(seconds=1) if completed else None,
        exit_code=exit_code if completed else None,
        server_signature="fake-sig",
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    return cmd


async def _make_heartbeats(
    db: AsyncSession,
    *,
    host_id: uuid.UUID,
    count: int,
    minute_step: int = 1,
) -> None:
    """Insert ``count`` heartbeats one minute apart, ending ~1 minute ago.

    Used by uptime tests — the endpoint counts distinct 1-minute buckets.
    """
    now = datetime.now(timezone.utc)
    for i in range(count):
        hb = Heartbeat(
            host_id=host_id,
            ts=now - timedelta(minutes=(i + 1) * minute_step),
            cpu_pct=10.0,
            mem_pct=50.0,
        )
        db.add(hb)
    await db.commit()


async def _make_audit(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_id: str = "n/a",
    group_name: str | None = None,
) -> AuditEvent:
    payload: dict = {}
    if group_name is not None:
        payload["group_name"] = group_name
    ev = AuditEvent(
        actor=actor,
        action=action,
        resource_type="generic",
        resource_id=resource_id,
        payload=payload,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev


# --------------------------------------------------------------------------- #
# /v1/dash/stats
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_stats_requires_auth(client: AsyncClient) -> None:
    """Missing session → 401."""
    _clear_user_override()
    resp = await client.get("/v1/dash/stats")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stats_invalid_range_returns_422(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Unknown ``range`` value rejected with 422."""
    admin = await _make_admin(test_db)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/stats?range=bogus")
    finally:
        _clear_user_override()
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stats_empty_fleet_returns_zeros(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """No hosts → fully zeroed response with the requested range echoed back."""
    admin = await _make_admin(test_db)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/stats?range=24h")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "24h"
    assert body["fleet"]["total_hosts"] == 0
    assert body["fleet"]["uptime_percent"] == 0.0
    assert body["commands"]["total"] == 0
    assert body["commands"]["success_rate"] == 0.0
    assert body["commands"]["daily"] == []
    assert body["heartbeats"]["total"] == 0
    assert body["uptime_per_host"] == []
    assert body["audit_summary"]["total_events"] == 0


@pytest.mark.asyncio
async def test_stats_fleet_counts(client: AsyncClient, test_db: AsyncSession) -> None:
    """Fleet section reflects online/offline classification at the cutoff."""
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="online", last_seen_s_ago=10)
    await _make_host(test_db, hostname="offline-old", last_seen_s_ago=900)
    await _make_host(test_db, hostname="never", last_seen_s_ago=None)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/stats?range=24h")
    finally:
        _clear_user_override()

    body = resp.json()
    assert body["fleet"]["total_hosts"] == 3
    assert body["fleet"]["online_now"] == 1
    assert body["fleet"]["offline_now"] == 2


@pytest.mark.asyncio
async def test_stats_commands_success_rate_and_by_type(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Commands roll-up: total / succeeded / failed / pending + by_type buckets."""
    admin = await _make_admin(test_db)
    host = await _make_host(test_db, hostname="h-cmds")
    issued = datetime.now(timezone.utc) - timedelta(hours=2)
    await _make_command(test_db, host_id=host.id, exit_code=0, issued_at=issued)
    await _make_command(test_db, host_id=host.id, exit_code=0, issued_at=issued)
    await _make_command(
        test_db, host_id=host.id, command_type="script", exit_code=1, issued_at=issued
    )
    await _make_command(
        test_db, host_id=host.id, exit_code=None, issued_at=issued, completed=False
    )
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/stats?range=24h")
    finally:
        _clear_user_override()

    body = resp.json()
    cmds = body["commands"]
    assert cmds["total"] == 4
    assert cmds["succeeded"] == 2
    assert cmds["failed"] == 1
    assert cmds["pending"] == 1
    assert cmds["success_rate"] == 0.5  # 2/4
    by_type = {row["type"]: row["count"] for row in cmds["by_type"]}
    assert by_type == {"shell": 3, "script": 1}


@pytest.mark.asyncio
async def test_stats_uptime_per_host(client: AsyncClient, test_db: AsyncSession) -> None:
    """Per-host uptime ratio derived from distinct 1-minute heartbeat buckets."""
    admin = await _make_admin(test_db)
    host_a = await _make_host(test_db, hostname="alpha")
    host_b = await _make_host(test_db, hostname="bravo")
    # 24h range = 1440 minutes. 60 minutes worth of heartbeats → ~4.17%.
    await _make_heartbeats(test_db, host_id=host_a.id, count=60)
    # No heartbeats for bravo → 0% uptime, 1440 downtime minutes.
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/stats?range=24h")
    finally:
        _clear_user_override()

    body = resp.json()
    by_host = {row["hostname"]: row for row in body["uptime_per_host"]}
    assert by_host["alpha"]["uptime_percent"] > 0
    assert by_host["alpha"]["downtime_minutes"] < 1440
    assert by_host["bravo"]["uptime_percent"] == 0.0
    assert by_host["bravo"]["downtime_minutes"] == 1440


@pytest.mark.asyncio
async def test_stats_viewer_scoped_to_own_groups(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """A viewer must not see hosts / commands outside their accessible groups."""
    viewer = await _make_viewer(test_db, groups=["family"])
    fam_host = await _make_host(test_db, hostname="fam-1", group="family")
    prod_host = await _make_host(test_db, hostname="prod-1", group="prod")
    issued = datetime.now(timezone.utc) - timedelta(hours=1)
    await _make_command(test_db, host_id=fam_host.id, exit_code=0, issued_at=issued)
    await _make_command(test_db, host_id=prod_host.id, exit_code=0, issued_at=issued)
    _override_user(viewer)

    try:
        resp = await client.get("/v1/dash/stats?range=24h")
    finally:
        _clear_user_override()

    body = resp.json()
    assert body["fleet"]["total_hosts"] == 1
    assert {row["hostname"] for row in body["uptime_per_host"]} == {"fam-1"}
    # Only the family-host command is visible
    assert body["commands"]["total"] == 1


@pytest.mark.asyncio
async def test_stats_audit_summary_breakdown(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Audit breakdown returns top actions + actors with descending counts."""
    admin = await _make_admin(test_db)
    for _ in range(3):
        await _make_audit(test_db, actor="alice@x", action="settings.user.create")
    for _ in range(2):
        await _make_audit(test_db, actor="bob@x", action="host.delete")
    await _make_audit(test_db, actor="alice@x", action="host.delete")
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/stats?range=7d")
    finally:
        _clear_user_override()

    body = resp.json()
    audit = body["audit_summary"]
    assert audit["total_events"] == 6
    # Sorted by count desc
    actions = [row["action"] for row in audit["by_action"]]
    assert actions[0] in {"settings.user.create", "host.delete"}
    actors = {row["actor"]: row["count"] for row in audit["by_actor"]}
    assert actors["alice@x"] == 4
    assert actors["bob@x"] == 2


@pytest.mark.asyncio
async def test_stats_range_echoed_back(client: AsyncClient, test_db: AsyncSession) -> None:
    """Every accepted range key is returned verbatim in the response envelope."""
    admin = await _make_admin(test_db)
    _override_user(admin)
    try:
        for r in ("24h", "7d", "30d", "90d"):
            resp = await client.get(f"/v1/dash/stats?range={r}")
            assert resp.status_code == 200, r
            assert resp.json()["range"] == r
    finally:
        _clear_user_override()
