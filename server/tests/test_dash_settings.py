"""Tests for the dashboard settings API (ADR-0009 Phase 4).

Exercises ``/v1/dash/settings/{groups,users}``:
- admin reaches every endpoint
- non-admin (viewer, operator) is rejected with 403
- validation errors (bad names, unknown groups, duplicate emails)
- 409 on deleting a group that still has hosts
- self-protection (admin cannot delete or demote themselves)

Same fake-auth approach as test_dash_api/test_dash_phase2: we override the
``current_user`` dependency at the app level. Because ``require_admin``
itself wraps ``current_user``, this propagates correctly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import Group, Host, User


# --------------------------------------------------------------------------- #
# Auth helpers
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


async def _make_group(db: AsyncSession, name: str, *, description: str | None = None) -> Group:
    g = Group(
        name=name,
        description=description,
        access_users=[],
        auto_distribute_keys=True,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return g


async def _make_host(db: AsyncSession, *, hostname: str, group: str) -> Host:
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


# --------------------------------------------------------------------------- #
# Auth gating
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_viewer_blocked_from_settings(client: AsyncClient, test_db: AsyncSession) -> None:
    viewer = await _make_user(test_db, role="viewer", groups=["prod"])
    _override_user(viewer)
    try:
        for path in (
            "/v1/dash/settings/groups",
            "/v1/dash/settings/users",
        ):
            r = await client.get(path)
            assert r.status_code == 403, (path, r.text)

        r = await client.post(
            "/v1/dash/settings/groups",
            json={"name": "newgroup"},
        )
        assert r.status_code == 403

        r = await client.post(
            "/v1/dash/settings/users",
            json={"email": "x@test.local", "role": "viewer"},
        )
        assert r.status_code == 403
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_blocked_from_settings(client: AsyncClient, test_db: AsyncSession) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    _override_user(op)
    try:
        r = await client.get("/v1/dash/settings/groups")
        assert r.status_code == 403
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_lists_groups_with_counts(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    await _make_group(test_db, "prod", description="production")
    await _make_group(test_db, "stage")
    await _make_host(test_db, hostname="h1", group="prod")
    await _make_host(test_db, hostname="h2", group="prod")
    # A viewer who only sees prod — should bump prod's user_count.
    await _make_user(test_db, role="viewer", groups=["prod"])

    _override_user(admin)
    try:
        r = await client.get("/v1/dash/settings/groups")
        assert r.status_code == 200, r.text
        data = r.json()
        by_name = {g["name"]: g for g in data["groups"]}
        assert set(by_name.keys()) == {"prod", "stage"}
        assert by_name["prod"]["host_count"] == 2
        assert by_name["prod"]["user_count"] == 1
        assert by_name["stage"]["host_count"] == 0
        assert by_name["stage"]["user_count"] == 0
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_create_group_happy(client: AsyncClient, test_db: AsyncSession) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/settings/groups",
            json={"name": "alpha", "description": "team alpha"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "alpha"
        assert body["description"] == "team alpha"
        assert body["host_count"] == 0
        assert body["user_count"] == 0

        # second create -> 409
        r2 = await client.post(
            "/v1/dash/settings/groups",
            json={"name": "alpha"},
        )
        assert r2.status_code == 409
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_create_group_rejects_bad_name(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        for bad in ("", "has space", "_starts_underscore", "x" * 64, "bad/slash"):
            r = await client.post("/v1/dash/settings/groups", json={"name": bad})
            assert r.status_code == 422, (bad, r.status_code, r.text)
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_delete_group_with_hosts_returns_409(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    await _make_group(test_db, "prod")
    await _make_host(test_db, hostname="h1", group="prod")
    _override_user(admin)
    try:
        r = await client.delete("/v1/dash/settings/groups/prod")
        assert r.status_code == 409, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_delete_empty_group_succeeds(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    await _make_group(test_db, "ephemeral")
    _override_user(admin)
    try:
        r = await client.delete("/v1/dash/settings/groups/ephemeral")
        assert r.status_code == 204

        # idempotent? No — second call is 404
        r2 = await client.delete("/v1/dash/settings/groups/ephemeral")
        assert r2.status_code == 404
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_lists_users(client: AsyncClient, test_db: AsyncSession) -> None:
    admin = await _make_user(test_db, role="admin", email="root@test.local")
    await _make_user(test_db, role="viewer", groups=["prod"], email="v1@test.local")
    _override_user(admin)
    try:
        r = await client.get("/v1/dash/settings/users")
        assert r.status_code == 200, r.text
        emails = {u["email"] for u in r.json()["users"]}
        assert {"root@test.local", "v1@test.local"} <= emails
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_create_user_happy(client: AsyncClient, test_db: AsyncSession) -> None:
    admin = await _make_user(test_db, role="admin")
    await _make_group(test_db, "prod")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/settings/users",
            json={
                "email": "new@test.local",
                "name": "New Person",
                "role": "operator",
                "groups": ["prod"],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["email"] == "new@test.local"
        assert body["role"] == "operator"
        assert body["groups"] == ["prod"]
        assert body["is_active"] is True

        # duplicate -> 409
        r2 = await client.post(
            "/v1/dash/settings/users",
            json={"email": "new@test.local", "role": "viewer"},
        )
        assert r2.status_code == 409
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_create_user_rejects_unknown_group(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/settings/users",
            json={"email": "ghost@test.local", "groups": ["does-not-exist"]},
        )
        assert r.status_code == 400, r.text
        assert "Unknown group" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_create_user_rejects_bad_role(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/settings/users",
            json={"email": "x@test.local", "role": "superhacker"},
        )
        assert r.status_code == 422
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_update_user_role_and_groups(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="viewer", groups=[])
    await _make_group(test_db, "prod")
    await _make_group(test_db, "stage")

    _override_user(admin)
    try:
        r = await client.patch(
            f"/v1/dash/settings/users/{target.id}",
            json={"role": "operator", "groups": ["prod", "stage"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "operator"
        assert set(body["groups"]) == {"prod", "stage"}
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_admin_cannot_demote_self(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.patch(
            f"/v1/dash/settings/users/{admin.id}",
            json={"role": "viewer"},
        )
        assert r.status_code == 400
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/settings/users/{admin.id}")
        assert r.status_code == 400
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_delete_user_happy(client: AsyncClient, test_db: AsyncSession) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="viewer")
    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/settings/users/{target.id}")
        assert r.status_code == 204

        # second call -> 404
        r2 = await client.delete(f"/v1/dash/settings/users/{target.id}")
        assert r2.status_code == 404
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_update_user_unknown_group_rejected(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="viewer")
    _override_user(admin)
    try:
        r = await client.patch(
            f"/v1/dash/settings/users/{target.id}",
            json={"groups": ["nope"]},
        )
        assert r.status_code == 400
    finally:
        _clear_user_override()
