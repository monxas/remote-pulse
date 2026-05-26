"""Tests for ``DELETE /v1/dash/hosts/{host_id}`` (ADR-0009 host.delete gate).

Covers:

- Admin can delete any host -> 204 + row gone + audit emitted
- Cascade behaviour: dependent rows (ssh_keys, commands, agent_versions,
  heartbeats, metric_samples) are wiped too.
- Operator with matching ``host.delete`` grant -> 204
- Operator with wildcard grant -> 204
- Operator without grant -> 403
- Operator with grant for a *different* group -> 403
- Non-existent host -> 404 (collapsed from access-denied to avoid leaking
  existence across tenants)
- Host in a group the caller can't see -> 404 (same anti-probe behaviour)
- Audit row carries ``hostname`` + ``group_name`` in payload, action is
  the canonical ``host.delete``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import (
    AgentVersion,
    AuditEvent,
    Command,
    Group,
    Heartbeat,
    Host,
    MetricSample,
    SSHKey,
    User,
    UserPermission,
)


# --------------------------------------------------------------------------- #
# Helpers (mirror style of test_user_permissions.py / test_dash_settings.py).
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    async def _fake() -> User:
        return user

    app.dependency_overrides[current_user] = _fake


def _clear_user_override() -> None:
    app.dependency_overrides.pop(current_user, None)


async def _make_user(
    db: AsyncSession,
    *,
    role: str = "admin",
    groups: list[str] | None = None,
    email: str | None = None,
) -> User:
    user = User(
        pocketid_sub=f"{role}-{uuid.uuid4().hex[:8]}",
        email=email or f"{role}-{uuid.uuid4().hex[:8]}@test.local",
        name=role.title(),
        role=role,
        accessible_groups=groups or [],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_group(db: AsyncSession, name: str) -> Group:
    g = Group(name=name, description=None, access_users=[], auto_distribute_keys=True)
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return g


async def _make_host(
    db: AsyncSession,
    *,
    hostname: str = "host-x",
    group: str | None = "prod",
) -> Host:
    h = Host(
        hostname=hostname,
        os="linux",
        arch="x86_64",
        agent_version="0.0.0-test",
        group_name=group,
        capabilities={},
        extra={},
        enrolled_at=datetime.now(timezone.utc),
    )
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _grant(
    db: AsyncSession,
    user: User,
    *,
    action: str,
    scope: str,
) -> None:
    db.add(
        UserPermission(
            user_id=user.id,
            action=action,
            scope=scope,
            granted_by="admin@test.local",
        )
    )
    await db.commit()


async def _seed_host_with_dependents(
    db: AsyncSession,
    *,
    hostname: str = "doomed",
    group: str = "prod",
) -> Host:
    """Create a host plus one row in every host-referencing table.

    Returns the host so callers can grab its id for the DELETE call.
    """
    await _make_group(db, group)
    host = await _make_host(db, hostname=hostname, group=group)

    db.add(
        SSHKey(
            host_id=host.id,
            user_name="root",
            pubkey="ssh-ed25519 AAAA...",
            fingerprint=f"SHA256:{uuid.uuid4().hex}",
            algorithm="ssh-ed25519",
        )
    )
    db.add(
        AgentVersion(
            host_id=host.id,
            agent_version="0.0.0-test",
            api_compat_min="1",
            api_compat_max="1",
        )
    )
    db.add(
        Command(
            host_id=host.id,
            issued_by="admin@test.local",
            command_type="agent.self_check",
            command_payload={},
            server_signature="sig",
        )
    )
    db.add(
        Heartbeat(
            host_id=host.id,
            ts=datetime.now(timezone.utc),
            cpu_pct=1.0,
            mem_pct=2.0,
        )
    )
    db.add(
        MetricSample(
            host_id=host.id,
            ts=datetime.now(timezone.utc),
            metric="cpu_per_core.0",
            value=42.0,
        )
    )
    await db.commit()
    return host


async def _audit_rows(db: AsyncSession, host_id: uuid.UUID) -> list[AuditEvent]:
    rows = (
        await db.execute(
            select(AuditEvent).where(AuditEvent.resource_id == str(host_id))
        )
    ).scalars().all()
    return list(rows)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_deletes_host_cascades_dependents(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _seed_host_with_dependents(test_db)

    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 204, r.text
    finally:
        _clear_user_override()

    # Host gone.
    assert (
        await test_db.execute(select(Host).where(Host.id == host.id))
    ).scalar_one_or_none() is None

    # Cascade verified: every dependent table is empty for this host.
    # FK CASCADE (ssh_keys, agent_versions, commands) fires on SQLite too
    # because the conftest fixture enables ``PRAGMA foreign_keys=ON``.
    assert (
        await test_db.execute(select(SSHKey).where(SSHKey.host_id == host.id))
    ).scalar_one_or_none() is None
    assert (
        await test_db.execute(
            select(AgentVersion).where(AgentVersion.host_id == host.id)
        )
    ).scalar_one_or_none() is None
    assert (
        await test_db.execute(select(Command).where(Command.host_id == host.id))
    ).scalar_one_or_none() is None

    # Time-series rows are wiped by the endpoint explicitly (no FK on
    # hypertables in production either).
    assert (
        await test_db.execute(
            select(Heartbeat).where(Heartbeat.host_id == host.id)
        )
    ).scalar_one_or_none() is None
    assert (
        await test_db.execute(
            select(MetricSample).where(MetricSample.host_id == host.id)
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_admin_delete_emits_audit_row(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _seed_host_with_dependents(
        test_db, hostname="audit-target", group="prod"
    )

    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 204
    finally:
        _clear_user_override()

    rows = await _audit_rows(test_db, host.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == admin.email
    assert row.action == "host.delete"
    assert row.resource_type == "host"
    assert row.resource_id == str(host.id)
    assert row.payload == {"hostname": "audit-target", "group_name": "prod"}


@pytest.mark.asyncio
async def test_operator_with_scoped_grant_can_delete(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _seed_host_with_dependents(test_db, group="prod")
    await _grant(test_db, op, action="host.delete", scope="prod")

    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 204, r.text
    finally:
        _clear_user_override()

    assert (
        await test_db.execute(select(Host).where(Host.id == host.id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_operator_with_wildcard_grant_can_delete(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    host = await _seed_host_with_dependents(test_db, group="stage")
    await _grant(test_db, op, action="host.delete", scope="*")

    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 204, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_without_grant_gets_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _seed_host_with_dependents(test_db, group="prod")

    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 403, r.text
        assert "host.delete" in r.json()["detail"]
    finally:
        _clear_user_override()

    # Host must still be present after the denial.
    assert (
        await test_db.execute(select(Host).where(Host.id == host.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_operator_with_grant_for_other_group_gets_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    host = await _seed_host_with_dependents(test_db, group="prod")
    # Grant scoped to "stage" — must NOT allow deletion of a prod host.
    await _grant(test_db, op, action="host.delete", scope="stage")

    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_nonexistent_host_returns_404(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    bogus = uuid.uuid4()

    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/hosts/{bogus}")
        assert r.status_code == 404, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_host_outside_accessible_groups_returns_404(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    # Operator can only see ``stage``; targets a host in ``prod``. We
    # deliberately collapse to 404 (not 403) so non-admins can't probe
    # which UUIDs exist outside their tenant.
    op = await _make_user(test_db, role="operator", groups=["stage"])
    # Even with the permission, accessible-group filter denies visibility.
    await _grant(test_db, op, action="host.delete", scope="*")
    host = await _seed_host_with_dependents(test_db, group="prod")

    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/hosts/{host.id}")
        assert r.status_code == 404, r.text
    finally:
        _clear_user_override()

    # Host must survive the probe attempt.
    assert (
        await test_db.execute(select(Host).where(Host.id == host.id))
    ).scalar_one_or_none() is not None
