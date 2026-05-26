"""Tests for the server-side audit trail on settings mutations.

Settings endpoints (``/v1/dash/settings/{groups,users}``) write an
``audit_events`` row inside the same transaction as the mutation. Those
rows must surface in ``GET /v1/dash/audit`` alongside the synthetic
timeline derived from commands / hosts / enrollments.

We reuse the fake-auth approach from test_dash_settings.py.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import AuditEvent, Group, User


# --------------------------------------------------------------------------- #
# Helpers (mirrored from test_dash_settings.py, kept local to keep this file
# self-contained — they're tiny and the duplication isn't worth a shared
# fixture today).
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


async def _audit_rows(db: AsyncSession) -> list[AuditEvent]:
    rows = (
        (await db.execute(select(AuditEvent).order_by(AuditEvent.ts)))
        .scalars()
        .all()
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Group mutations write audit rows
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_group_create_writes_audit_row(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/settings/groups",
            json={"name": "alpha", "description": "team alpha"},
        )
        assert r.status_code == 201, r.text

        rows = await _audit_rows(test_db)
        creates = [a for a in rows if a.action == "settings.group.create"]
        assert len(creates) == 1
        ev = creates[0]
        assert ev.actor == "root@test.local"
        assert ev.resource_type == "group"
        assert ev.resource_id == "alpha"
        assert ev.payload["name"] == "alpha"
        assert ev.payload["description"] == "team alpha"
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_group_delete_writes_audit_row(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    await _make_group(test_db, "ephemeral")
    _override_user(admin)
    try:
        r = await client.delete("/v1/dash/settings/groups/ephemeral")
        assert r.status_code == 204

        rows = await _audit_rows(test_db)
        deletes = [a for a in rows if a.action == "settings.group.delete"]
        assert len(deletes) == 1
        assert deletes[0].resource_id == "ephemeral"
        assert deletes[0].actor == "root@test.local"
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# User mutations write audit rows
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_user_create_writes_audit_row(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    await _make_group(test_db, "prod")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/settings/users",
            json={
                "email": "new@test.local",
                "role": "operator",
                "groups": ["prod"],
            },
        )
        assert r.status_code == 201, r.text
        new_id = r.json()["id"]

        rows = await _audit_rows(test_db)
        creates = [a for a in rows if a.action == "settings.user.create"]
        assert len(creates) == 1
        ev = creates[0]
        assert ev.resource_id == new_id
        assert ev.payload["email"] == "new@test.local"
        assert ev.payload["role"] == "operator"
        assert ev.payload["groups"] == ["prod"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_user_update_writes_audit_with_before_after(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    target = await _make_user(test_db, role="viewer", groups=[])
    await _make_group(test_db, "prod")
    _override_user(admin)
    try:
        r = await client.patch(
            f"/v1/dash/settings/users/{target.id}",
            json={"role": "operator", "groups": ["prod"]},
        )
        assert r.status_code == 200, r.text

        rows = await _audit_rows(test_db)
        updates = [a for a in rows if a.action == "settings.user.update"]
        assert len(updates) == 1
        ev = updates[0]
        assert ev.resource_id == str(target.id)
        changes = ev.payload["changes"]
        assert changes["role"] == {"before": "viewer", "after": "operator"}
        assert changes["groups"] == {"before": [], "after": ["prod"]}
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_user_update_noop_emits_no_audit(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """PATCH that doesn't actually change anything must not pollute the log."""
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    target = await _make_user(test_db, role="viewer", groups=[])
    _override_user(admin)
    try:
        r = await client.patch(
            f"/v1/dash/settings/users/{target.id}",
            json={"role": "viewer"},  # already viewer
        )
        assert r.status_code == 200

        rows = await _audit_rows(test_db)
        assert [a for a in rows if a.action == "settings.user.update"] == []
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_user_delete_writes_audit_row(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    target = await _make_user(
        test_db, role="viewer", email="goner@test.local"
    )
    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/settings/users/{target.id}")
        assert r.status_code == 204

        rows = await _audit_rows(test_db)
        deletes = [a for a in rows if a.action == "settings.user.delete"]
        assert len(deletes) == 1
        assert deletes[0].resource_id == str(target.id)
        assert deletes[0].payload["email"] == "goner@test.local"
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Non-admin rejection writes no audit
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_non_admin_rejection_writes_no_audit(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    viewer = await _make_user(test_db, role="viewer", groups=["prod"])
    _override_user(viewer)
    try:
        r = await client.post(
            "/v1/dash/settings/groups",
            json={"name": "should-not-exist"},
        )
        assert r.status_code == 403

        rows = await _audit_rows(test_db)
        assert rows == []
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# /v1/dash/audit surfaces the real rows
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_audit_endpoint_returns_settings_events(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    _override_user(admin)
    try:
        # Two mutations → two audit rows.
        r1 = await client.post(
            "/v1/dash/settings/groups", json={"name": "alpha"}
        )
        assert r1.status_code == 201
        r2 = await client.post(
            "/v1/dash/settings/groups", json={"name": "beta"}
        )
        assert r2.status_code == 201

        r = await client.get("/v1/dash/audit", params={"limit": 50})
        assert r.status_code == 200, r.text
        body = r.json()
        actions = [e["action"] for e in body["events"]]
        # Both creates must appear; ts DESC means newest first.
        assert actions.count("settings.group.create") == 2
        assert actions.index("settings.group.create") < len(actions)

        # Resource ids and metadata are propagated.
        creates = [e for e in body["events"] if e["action"] == "settings.group.create"]
        ids = {e["target_id"] for e in creates}
        assert ids == {"alpha", "beta"}
        for ev in creates:
            assert ev["actor"] == "root@test.local"
            assert ev["target_type"] == "group"
            assert ev["metadata"].get("name") in {"alpha", "beta"}
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_audit_endpoint_filters_by_action(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r1 = await client.post(
            "/v1/dash/settings/groups", json={"name": "alpha"}
        )
        assert r1.status_code == 201

        r = await client.get(
            "/v1/dash/audit",
            params={"action": "settings.group.create"},
        )
        assert r.status_code == 200, r.text
        events = r.json()["events"]
        assert len(events) == 1
        assert events[0]["action"] == "settings.group.create"
        assert events[0]["target_id"] == "alpha"
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_audit_endpoint_filters_by_target_type_group(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r1 = await client.post(
            "/v1/dash/settings/groups", json={"name": "alpha"}
        )
        assert r1.status_code == 201

        r = await client.get(
            "/v1/dash/audit", params={"target_type": "group"}
        )
        assert r.status_code == 200, r.text
        events = r.json()["events"]
        assert all(e["target_type"] == "group" for e in events)
        assert any(e["target_id"] == "alpha" for e in events)
    finally:
        _clear_user_override()
