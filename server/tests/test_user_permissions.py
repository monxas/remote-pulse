"""Tests for row-level user_permissions (ADR-0009 Settings polish).

Covers the new ``/v1/dash/settings/users/{id}/permissions`` endpoints and
the enforcement they unlock on the privileged endpoints:

- admin grant / list / revoke happy paths
- non-admin gets 403 on every endpoint
- duplicate grant -> 409
- unknown action -> 422 (Pydantic enum guard)
- ``command.issue`` gate (POST /v1/admin/commands):
    - admin always passes
    - operator without permission -> 403
    - operator with permission scoped to host's group -> 201
- ``command.approve`` gate (POST /v1/dash/approvals/{id}/approve|reject):
    - admin always passes
    - operator without permission -> 403
    - wildcard / scoped grants behave consistently with the resolver
- ``enroll.create`` gate (POST /v1/dash/enroll/links):
    - admin always passes
    - operator without permission -> 403
    - wildcard / scoped grants behave consistently with the resolver

We reuse the same dependency-override pattern as ``test_dash_settings.py``:
the ``current_user`` dep is swapped at app level which propagates through
``require_admin`` / ``require_operator_or_admin``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.config import settings as _settings
from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import Command, Group, Host, User, UserPermission
from rp_server.permissions import (
    ALLOWED_ACTIONS,
    is_action_allowed,
    user_has_permission,
)


@pytest.fixture(autouse=True)
def _isolated_signing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the signing key into a writable per-test directory.

    Without this, ``ServerSigningKey.load_or_generate`` defaults to
    ``/etc/rp`` which isn't writable from the dev shell. The router holds
    a module-level singleton, so we also clear it before each test.
    """
    from rp_server.routers import commands as _commands
    from rp_server.signing import ServerSigningKey

    _commands._signing_key = ServerSigningKey.load_or_generate(tmp_path)


# --------------------------------------------------------------------------- #
# Helpers (mirror test_dash_settings.py so the two suites stay legible side
# by side; deliberately copied rather than shared to keep the fixtures small).
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
# Permission resolver unit tests (no HTTP)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_bypasses_permission_check(test_db: AsyncSession) -> None:
    admin = await _make_user(test_db, role="admin")
    assert await user_has_permission(test_db, admin, "command.issue", "prod") is True
    assert await user_has_permission(test_db, admin, "anything-at-all", None) is True


@pytest.mark.asyncio
async def test_operator_without_grant_denied(test_db: AsyncSession) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    assert await user_has_permission(test_db, op, "command.issue", "prod") is False


@pytest.mark.asyncio
async def test_operator_with_wildcard_scope_allowed(test_db: AsyncSession) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.issue",
            scope="*",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    assert await user_has_permission(test_db, op, "command.issue", "prod") is True
    # Wildcard also covers a different group
    assert await user_has_permission(test_db, op, "command.issue", "stage") is True


@pytest.mark.asyncio
async def test_operator_with_scoped_grant_only_matches_scope(
    test_db: AsyncSession,
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.issue",
            scope="prod",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    assert await user_has_permission(test_db, op, "command.issue", "prod") is True
    assert await user_has_permission(test_db, op, "command.issue", "stage") is False


@pytest.mark.asyncio
async def test_inactive_user_never_authorised(test_db: AsyncSession) -> None:
    op = await _make_user(test_db, role="operator")
    op.is_active = False
    await test_db.commit()
    # Even with a matching grant, deactivation overrides.
    test_db.add(
        UserPermission(
            user_id=op.id, action="command.issue", scope="*", granted_by="x"
        )
    )
    await test_db.commit()
    assert await user_has_permission(test_db, op, "command.issue", "prod") is False


def test_allowed_actions_enum_membership() -> None:
    # Sanity check the canonical enum stays in sync with what the UI ships.
    assert is_action_allowed("command.issue")
    assert is_action_allowed("command.approve")
    assert not is_action_allowed("command.delete-the-database")
    assert ALLOWED_ACTIONS == {
        "command.issue",
        "command.approve",
        "host.delete",
        "enroll.create",
        "enroll.revoke",
    }


# --------------------------------------------------------------------------- #
# HTTP: grant / list / revoke (admin-only)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_grants_permission(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="operator", groups=["prod"])
    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/settings/users/{target.id}/permissions",
            json={"action": "command.issue", "scope": "prod"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["action"] == "command.issue"
        assert body["scope"] == "prod"
        assert body["granted_by"] == admin.email
        assert body["user_id"] == str(target.id)

        # Listing returns the row + the canonical action enum
        r2 = await client.get(
            f"/v1/dash/settings/users/{target.id}/permissions"
        )
        assert r2.status_code == 200
        payload = r2.json()
        assert len(payload["permissions"]) == 1
        assert payload["allowed_actions"] == sorted(ALLOWED_ACTIONS)
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_non_admin_cannot_grant_or_list(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    target = await _make_user(test_db, role="viewer")
    _override_user(op)
    try:
        r = await client.get(f"/v1/dash/settings/users/{target.id}/permissions")
        assert r.status_code == 403

        r = await client.post(
            f"/v1/dash/settings/users/{target.id}/permissions",
            json={"action": "command.issue", "scope": "*"},
        )
        assert r.status_code == 403
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_grant_unknown_action_rejected(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="operator")
    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/settings/users/{target.id}/permissions",
            json={"action": "command.nuke-everything", "scope": "*"},
        )
        # Pydantic field validation -> 422
        assert r.status_code == 422
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_grant_duplicate_returns_409(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="operator")
    _override_user(admin)
    try:
        r1 = await client.post(
            f"/v1/dash/settings/users/{target.id}/permissions",
            json={"action": "command.issue", "scope": "*"},
        )
        assert r1.status_code == 201
        r2 = await client.post(
            f"/v1/dash/settings/users/{target.id}/permissions",
            json={"action": "command.issue", "scope": "*"},
        )
        assert r2.status_code == 409
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_revoke_permission_succeeds(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="operator")
    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/settings/users/{target.id}/permissions",
            json={"action": "command.issue", "scope": "*"},
        )
        assert r.status_code == 201
        pid = r.json()["id"]

        r2 = await client.delete(
            f"/v1/dash/settings/users/{target.id}/permissions/{pid}"
        )
        assert r2.status_code == 204

        # Subsequent revoke is 404
        r3 = await client.delete(
            f"/v1/dash/settings/users/{target.id}/permissions/{pid}"
        )
        assert r3.status_code == 404
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_grant_for_unknown_user_returns_404(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        ghost = uuid.uuid4()
        r = await client.post(
            f"/v1/dash/settings/users/{ghost}/permissions",
            json={"action": "command.issue", "scope": "*"},
        )
        assert r.status_code == 404
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Enforcement on POST /v1/admin/commands
# --------------------------------------------------------------------------- #


async def _issue_command_payload(host_id: uuid.UUID) -> dict[str, Any]:
    return {
        "host_id": str(host_id),
        "command_type": "exec_shell",
        "command_payload": {"cmd": "uptime"},
        "timeout_s": 30,
        "expires_in_s": 60,
    }


@pytest.mark.asyncio
async def test_admin_can_issue_command_without_grant(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h1", group="prod")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/admin/commands",
            json=await _issue_command_payload(host.id),
        )
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_without_permission_blocked(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h1", group="prod")
    _override_user(op)
    try:
        r = await client.post(
            "/v1/admin/commands",
            json=await _issue_command_payload(host.id),
        )
        assert r.status_code == 403, r.text
        assert "command.issue" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_scoped_permission_allowed(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h1", group="prod")
    # Grant directly via ORM (faster than the API + already covered above)
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.issue",
            scope="prod",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        r = await client.post(
            "/v1/admin/commands",
            json=await _issue_command_payload(host.id),
        )
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_wrong_scope_blocked(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    await _make_group(test_db, "prod")
    await _make_group(test_db, "stage")
    host = await _make_host(test_db, hostname="h1", group="prod")
    # Grant for stage only — the host lives in prod so this should NOT pass.
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.issue",
            scope="stage",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        r = await client.post(
            "/v1/admin/commands",
            json=await _issue_command_payload(host.id),
        )
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Enforcement on POST /v1/dash/approvals/{id}/approve|reject
#
# ``approval_id`` is the command id (see dash_commands._resolve_approval). We
# seed a Command in "pending approval" state (approval_token set,
# human_approved=False, rejected_reason=None) and exercise both decisions.
# --------------------------------------------------------------------------- #


async def _make_pending_command(
    db: AsyncSession,
    *,
    host: Host,
    issued_by: str = "admin@test.local",
) -> Command:
    """Insert a Command in the 'awaiting approval' state for the given host."""
    now = datetime.now(timezone.utc)
    cmd = Command(
        host_id=host.id,
        issued_by=issued_by,
        command_type="exec_shell",
        command_payload={"cmd": "uptime"},
        server_signature="sig-stub",  # not validated by the approve endpoint
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=now,
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    return cmd


@pytest.mark.asyncio
async def test_admin_can_approve_without_grant(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h-approve-admin", group="prod")
    cmd = await _make_pending_command(test_db, host=host)

    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/approvals/{cmd.id}/approve",
            json={"reason": "lgtm"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_without_approve_permission_blocked(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    # ``accessible_groups`` includes the host's group so the 404 visibility
    # guard in _load_command_for_user does not short-circuit the test; the
    # only thing standing between the operator and a 200 is the new ACL.
    op = await _make_user(test_db, role="operator", groups=["prod"])
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h-approve-op-deny", group="prod")
    cmd = await _make_pending_command(test_db, host=host)

    _override_user(op)
    try:
        r = await client.post(
            f"/v1/dash/approvals/{cmd.id}/approve",
            json={"reason": "lgtm"},
        )
        assert r.status_code == 403, r.text
        assert "command.approve" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_wildcard_can_approve(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h-approve-wild", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.approve",
            scope="*",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        r = await client.post(
            f"/v1/dash/approvals/{cmd.id}/approve",
            json={"reason": "lgtm"},
        )
        assert r.status_code == 200, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_scoped_grant_can_reject(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    # Use the reject endpoint to exercise the second wrapper too; both must
    # share the same ``command.approve`` permission.
    op = await _make_user(test_db, role="operator", groups=["prod"])
    await _make_group(test_db, "prod")
    host = await _make_host(test_db, hostname="h-reject-scoped", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.approve",
            scope="prod",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        r = await client.post(
            f"/v1/dash/approvals/{cmd.id}/reject",
            json={"reason": "no thanks"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_wrong_scope_blocked_from_approve(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    await _make_group(test_db, "prod")
    await _make_group(test_db, "stage")
    host = await _make_host(test_db, hostname="h-approve-wrong", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    # Grant scoped to stage only — host lives in prod, so resolution must fail.
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="command.approve",
            scope="stage",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        r = await client.post(
            f"/v1/dash/approvals/{cmd.id}/approve",
            json={"reason": "lgtm"},
        )
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Enforcement on POST /v1/dash/enroll/links
# --------------------------------------------------------------------------- #


@pytest.fixture
def _allowlisted_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``server_url`` into the dash_enroll install allowlist."""
    monkeypatch.setattr(_settings, "server_url", "https://rp.monxas.casa")


@pytest.mark.asyncio
async def test_admin_can_create_enroll_link_without_grant(
    client: AsyncClient,
    test_db: AsyncSession,
    _allowlisted_server_url: None,
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "family", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_without_enroll_permission_blocked(
    client: AsyncClient,
    test_db: AsyncSession,
    _allowlisted_server_url: None,
) -> None:
    op = await _make_user(test_db, role="operator", groups=["family"])
    _override_user(op)
    try:
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "family", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 403, r.text
        assert "enroll.create" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_wildcard_can_create_enroll_link(
    client: AsyncClient,
    test_db: AsyncSession,
    _allowlisted_server_url: None,
) -> None:
    op = await _make_user(test_db, role="operator", groups=["family"])
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="enroll.create",
            scope="*",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "family", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 201, r.text
        # Wildcard also works for a different group
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "rfrobredo", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_with_scoped_grant_can_create_for_that_group_only(
    client: AsyncClient,
    test_db: AsyncSession,
    _allowlisted_server_url: None,
) -> None:
    op = await _make_user(test_db, role="operator", groups=["family", "prod"])
    test_db.add(
        UserPermission(
            user_id=op.id,
            action="enroll.create",
            scope="family",
            granted_by="admin@test.local",
        )
    )
    await test_db.commit()

    _override_user(op)
    try:
        # Matching scope -> 201
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "family", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 201, r.text

        # Non-matching scope -> 403
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "prod", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()
