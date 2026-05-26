"""Coverage for the final permission gaps wired in ADR-0009 follow-up.

This module closes the three endpoints that previously relied on the legacy
role-based gate and now consult :mod:`rp_server.permissions`:

- ``POST   /v1/dash/commands``                — ``command.issue``
- ``POST   /v1/dash/commands/{id}/retry``     — ``command.issue``
- ``DELETE /v1/dash/enroll/links/{jti}``      — ``enroll.revoke``

For each endpoint we exercise the canonical matrix (admin bypass / operator
denied / operator with wildcard / operator with scoped match / operator with
scoped mismatch). Plus a couple of sanity asserts on the :data:`ALLOWED_ACTIONS`
enum membership and the ``GET ../permissions`` echo so the SPA stays in sync.

We deliberately mirror the fake-auth pattern from ``test_user_permissions.py``
and ``test_dash_phase2.py`` (override ``current_user`` at the app level, reuse
the in-memory SQLite ``test_db`` fixture from ``conftest.py``).
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
from rp_server.models import Command, Enrollment, Host, User, UserPermission
from rp_server.permissions import ALLOWED_ACTIONS


# --------------------------------------------------------------------------- #
# Signing key isolation (mirror test_dash_phase2 / test_user_permissions)
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _patch_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid writing the signing key under ``/etc/rp`` during tests.

    Both ``commands.py`` and ``dash_commands.py`` import ``get_signing_key``
    by name, so patching only one leaves the other module pointing at the
    real (file-writing) factory. We swap both.
    """
    from rp_server.routers import commands as commands_router
    from rp_server.routers import dash_commands as dash_commands_router

    class _FakeKey:
        def sign_command(
            self,
            command_id: str,
            command_type: str,
            payload: dict[str, Any],
            expires_at: datetime,
        ) -> str:
            return f"sig-{command_id}"

        def public_key_pem(self) -> bytes:  # pragma: no cover — unused here
            return b"-----BEGIN PUBLIC KEY-----\nstub\n-----END PUBLIC KEY-----\n"

    def _fake_get() -> _FakeKey:
        return _FakeKey()

    monkeypatch.setattr(commands_router, "get_signing_key", _fake_get)
    monkeypatch.setattr(dash_commands_router, "get_signing_key", _fake_get)


@pytest.fixture
def _allowlisted_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``server_url`` into the dash_enroll install allowlist."""
    monkeypatch.setattr(_settings, "server_url", "https://rp.monxas.casa")


# --------------------------------------------------------------------------- #
# Test helpers
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
) -> User:
    u = User(
        pocketid_sub=f"{role}-{uuid.uuid4().hex[:8]}",
        email=f"{role}-{uuid.uuid4().hex[:8]}@test.local",
        name=role.title(),
        role=role,
        accessible_groups=groups or [],
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_host(db: AsyncSession, *, hostname: str, group: str) -> Host:
    h = Host(
        hostname=hostname,
        os="linux",
        arch="x86_64",
        agent_version="1.0.0-test",
        group_name=group,
        capabilities={},
        extra={},
        enrolled_at=datetime.now(timezone.utc),
    )
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _make_pending_command(db: AsyncSession, *, host: Host) -> Command:
    """Insert a command in 'pending approval' state so retry has a row to clone."""
    cmd = Command(
        host_id=host.id,
        issued_by="seed@test.local",
        command_type="exec_shell",
        command_payload={"cmd": "uptime"},
        server_signature="sig-stub",
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=datetime.now(timezone.utc),
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    return cmd


async def _grant(
    db: AsyncSession, *, user: User, action: str, scope: str
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


async def _seed_enrollment(
    db: AsyncSession, *, group: str = "family"
) -> Enrollment:
    e = Enrollment(
        token_jti=str(uuid.uuid4()),
        issued_by="seed@test.local",
        group_name=group,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
        max_uses=3,
        used_count=0,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


def _issue_body(host_id: uuid.UUID, command_type: str = "exec_shell") -> dict:
    return {
        "host_ids": [str(host_id)],
        "command_type": command_type,
        "command_payload": {"cmd": "uptime"},
        # exec_shell isn't in REQUIRES_APPROVAL_BY_DEFAULT, so this lands in
        # the "approved" branch — exercises the more interesting code path.
        "requires_approval": False,
        "timeout_s": 30,
        "expires_in_s": 60,
    }


# --------------------------------------------------------------------------- #
# Enum sanity
# --------------------------------------------------------------------------- #


def test_enroll_revoke_in_allowed_actions() -> None:
    """Sanity-check that the new action made it into the canonical enum."""
    assert "enroll.revoke" in ALLOWED_ACTIONS
    assert "enroll.create" in ALLOWED_ACTIONS  # still there, separate action
    assert ALLOWED_ACTIONS == {
        "command.issue",
        "command.approve",
        "host.delete",
        "enroll.create",
        "enroll.revoke",
    }


@pytest.mark.asyncio
async def test_get_permissions_echoes_enroll_revoke(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """The Settings UI reads ``allowed_actions`` from the GET response.

    Asserting that the new action shows up there keeps the SPA in lock-step
    without it having to ship its own hard-coded enum.
    """
    admin = await _make_user(test_db, role="admin")
    target = await _make_user(test_db, role="operator")
    _override_user(admin)
    try:
        r = await client.get(
            f"/v1/dash/settings/users/{target.id}/permissions"
        )
        assert r.status_code == 200, r.text
        assert "enroll.revoke" in r.json()["allowed_actions"]
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# POST /v1/dash/commands  →  command.issue
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dash_issue_admin_bypasses(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="h-issue-admin", group="prod")
    _override_user(admin)
    try:
        r = await client.post("/v1/dash/commands", json=_issue_body(host.id))
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_issue_operator_without_grant_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    # Operator can see the group (so the 404 short-circuit doesn't fire), but
    # holds no row-level grant → 403 with the canonical error message.
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _make_host(test_db, hostname="h-issue-deny", group="prod")
    _override_user(op)
    try:
        r = await client.post("/v1/dash/commands", json=_issue_body(host.id))
        assert r.status_code == 403, r.text
        assert "command.issue" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_issue_operator_with_wildcard_201(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _make_host(test_db, hostname="h-issue-wild", group="prod")
    await _grant(test_db, user=op, action="command.issue", scope="*")
    _override_user(op)
    try:
        r = await client.post("/v1/dash/commands", json=_issue_body(host.id))
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_issue_operator_with_scoped_match_201(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _make_host(test_db, hostname="h-issue-scoped", group="prod")
    await _grant(test_db, user=op, action="command.issue", scope="prod")
    _override_user(op)
    try:
        r = await client.post("/v1/dash/commands", json=_issue_body(host.id))
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_issue_operator_with_scoped_mismatch_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    host = await _make_host(test_db, hostname="h-issue-wrong", group="prod")
    # Grant scoped to stage only — host lives in prod, must fail.
    await _grant(test_db, user=op, action="command.issue", scope="stage")
    _override_user(op)
    try:
        r = await client.post("/v1/dash/commands", json=_issue_body(host.id))
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# POST /v1/dash/commands/{id}/retry  →  command.issue
#
# Retry's permission scope is the ORIGINAL command's host group. We seed a
# pending command for each test so the ``_load_command_for_user`` lookup
# returns a row, then exercise the same 5-scenario matrix.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dash_retry_admin_bypasses(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="h-retry-admin", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    _override_user(admin)
    try:
        r = await client.post(f"/v1/dash/commands/{cmd.id}/retry")
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_retry_operator_without_grant_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _make_host(test_db, hostname="h-retry-deny", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    _override_user(op)
    try:
        r = await client.post(f"/v1/dash/commands/{cmd.id}/retry")
        assert r.status_code == 403, r.text
        assert "command.issue" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_retry_operator_with_wildcard_201(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _make_host(test_db, hostname="h-retry-wild", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    await _grant(test_db, user=op, action="command.issue", scope="*")
    _override_user(op)
    try:
        r = await client.post(f"/v1/dash/commands/{cmd.id}/retry")
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_retry_operator_with_scoped_match_201(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod"])
    host = await _make_host(test_db, hostname="h-retry-scoped", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    await _grant(test_db, user=op, action="command.issue", scope="prod")
    _override_user(op)
    try:
        r = await client.post(f"/v1/dash/commands/{cmd.id}/retry")
        assert r.status_code == 201, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_retry_operator_with_scoped_mismatch_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["prod", "stage"])
    host = await _make_host(test_db, hostname="h-retry-wrong", group="prod")
    cmd = await _make_pending_command(test_db, host=host)
    await _grant(test_db, user=op, action="command.issue", scope="stage")
    _override_user(op)
    try:
        r = await client.post(f"/v1/dash/commands/{cmd.id}/retry")
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# DELETE /v1/dash/enroll/links/{jti}  →  enroll.revoke
#
# Soft-revoke: row stays, ``expires_at`` collapses to now + ``used_count`` is
# bumped to ``max_uses``. We assert 204 for the allowed paths and 403 for the
# denied paths. The 404-wins-over-403 invariant is covered indirectly by the
# pre-existing ``test_revoke_unknown_link_returns_404`` test, plus the viewer
# happy-path tweak in ``test_dash_enroll_links.py``.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dash_revoke_admin_bypasses(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    e = await _seed_enrollment(test_db, group="family")
    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/enroll/links/{e.token_jti}")
        assert r.status_code == 204, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_revoke_operator_without_grant_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    # The row exists → permission check fires → 403 (no ``enroll.revoke`` grant).
    op = await _make_user(test_db, role="operator", groups=["family"])
    e = await _seed_enrollment(test_db, group="family")
    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/enroll/links/{e.token_jti}")
        assert r.status_code == 403, r.text
        assert "enroll.revoke" in r.json()["detail"]
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_revoke_operator_with_wildcard_204(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["family"])
    e = await _seed_enrollment(test_db, group="family")
    await _grant(test_db, user=op, action="enroll.revoke", scope="*")
    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/enroll/links/{e.token_jti}")
        assert r.status_code == 204, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_revoke_operator_with_scoped_match_204(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["family"])
    e = await _seed_enrollment(test_db, group="family")
    await _grant(test_db, user=op, action="enroll.revoke", scope="family")
    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/enroll/links/{e.token_jti}")
        assert r.status_code == 204, r.text
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_dash_revoke_operator_with_scoped_mismatch_403(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator", groups=["family", "prod"])
    e = await _seed_enrollment(test_db, group="family")
    # Grant for a different group — the row lives in "family" so this must fail.
    await _grant(test_db, user=op, action="enroll.revoke", scope="prod")
    _override_user(op)
    try:
        r = await client.delete(f"/v1/dash/enroll/links/{e.token_jti}")
        assert r.status_code == 403, r.text
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Separation: enroll.create and enroll.revoke are independent grants
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_enroll_create_grant_does_not_authorize_revoke(
    client: AsyncClient,
    test_db: AsyncSession,
    _allowlisted_server_url: None,
) -> None:
    """An operator with ``enroll.create`` but no ``enroll.revoke`` can issue
    links but not destroy them (and vice versa for the symmetric test).

    This is the whole point of splitting the two actions — see
    :mod:`rp_server.permissions` for the rationale.
    """
    op = await _make_user(test_db, role="operator", groups=["family"])
    await _grant(test_db, user=op, action="enroll.create", scope="*")
    # NOTE: no enroll.revoke grant.

    _override_user(op)
    try:
        # Create works.
        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "family", "ttl_hours": 6, "max_uses": 1},
        )
        assert r.status_code == 201, r.text
        created_jti = r.json()["token_jti"]

        # Revoke is denied.
        r = await client.delete(f"/v1/dash/enroll/links/{created_jti}")
        assert r.status_code == 403, r.text
        assert "enroll.revoke" in r.json()["detail"]
    finally:
        _clear_user_override()
