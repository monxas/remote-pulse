"""Tests for the SvelteKit dashboard JSON API — Phase 2 (ADR-0009).

Covers:
- ``/v1/dash/commands`` (list with cursor/filters, detail, retry)
- ``POST /v1/dash/commands`` (issue, one row per host_id, approval policy)
- ``/v1/dash/approvals/{id}/approve|reject`` (state changes + SSE)
- ``/v1/dash/approvals/pending``
- ``/v1/dash/audit`` (cursor, filters, source coverage, ACL)
- SSE: events fired by issue / approval actions reach subscribers

Like ``test_dash_api.py`` we override ``current_user`` to fake auth and use
the existing SQLite ``test_db`` fixture from ``conftest.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.events import event_bus
from rp_server.main import app
from rp_server.models import Command, Enrollment, Host, User
from rp_server.routers import commands as commands_router
from rp_server.routers import dash_commands as dash_commands_router


@pytest.fixture(autouse=True)
def _patch_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests run unprivileged; avoid writing the signing key to /etc/rp."""

    class _FakeKey:
        def sign_command(
            self,
            command_id: str,
            command_type: str,
            payload: dict[str, Any],
            expires_at: datetime,
        ) -> str:
            return f"sig-{command_id}"

        def public_key_pem(self) -> bytes:  # pragma: no cover — unused by router
            return b"-----BEGIN PUBLIC KEY-----\nstub\n-----END PUBLIC KEY-----\n"

    def _fake_get() -> _FakeKey:
        return _FakeKey()

    # dash_commands.py imported the symbol by name, so patch BOTH locations.
    monkeypatch.setattr(commands_router, "get_signing_key", _fake_get)
    monkeypatch.setattr(dash_commands_router, "get_signing_key", _fake_get)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    async def _fake_current_user() -> User:
        return user

    app.dependency_overrides[current_user] = _fake_current_user


def _clear_user_override() -> None:
    app.dependency_overrides.pop(current_user, None)


async def _make_user(
    db: AsyncSession, *, role: str = "admin", groups: list[str] | None = None
) -> User:
    user = User(
        pocketid_sub=f"{role}-{uuid.uuid4().hex[:8]}",
        email=f"{role}-{uuid.uuid4().hex[:8]}@test.local",
        name=role.title(),
        role=role,
        accessible_groups=groups or [],
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
    last_seen_s_ago: int | None = None,
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
        enrolled_at=now - timedelta(days=1),
    )
    db.add(host)
    await db.commit()
    await db.refresh(host)
    return host


async def _make_command(
    db: AsyncSession,
    *,
    host: Host,
    issued_by: str = "ops@test.local",
    command_type: str = "shell",
    payload: dict[str, Any] | None = None,
    issued_at: datetime | None = None,
    completed_at: datetime | None = None,
    exit_code: int | None = None,
    human_approved: bool = True,
    approval_token: uuid.UUID | None = None,
    rejected_reason: str | None = None,
    approval_requested_at: datetime | None = None,
    approval_responded_at: datetime | None = None,
    approved_by: str | None = None,
) -> Command:
    cmd = Command(
        host_id=host.id,
        issued_by=issued_by,
        command_type=command_type,
        command_payload=payload or {"cmd": "echo hello"},
        server_signature="test-signature-fixture",
        human_approved=human_approved,
        approval_token=approval_token,
        rejected_reason=rejected_reason,
        approval_requested_at=approval_requested_at,
        approval_responded_at=approval_responded_at,
        approved_by=approved_by,
    )
    if issued_at is not None:
        cmd.issued_at = issued_at
    if completed_at is not None:
        cmd.completed_at = completed_at
    if exit_code is not None:
        cmd.exit_code = exit_code
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    return cmd


# --------------------------------------------------------------------------- #
# GET /v1/dash/commands — list, filters, cursor
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_commands_list_returns_summaries(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Basic list returns host_hostname-enriched summaries with derived status."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="alpha", group="prod")
    cmd = await _make_command(
        test_db,
        host=host,
        completed_at=datetime.now(timezone.utc),
        exit_code=0,
    )
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/commands")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["next_cursor"] is None
    assert len(body["commands"]) == 1
    row = body["commands"][0]
    assert row["id"] == str(cmd.id)
    assert row["host_hostname"] == "alpha"
    assert row["host_group"] == "prod"
    assert row["status"] == "succeeded"


@pytest.mark.asyncio
async def test_commands_list_cursor_pagination(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Walking the cursor returns every command exactly once, newest-first."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="paginate-host", group="prod")
    base = datetime.now(timezone.utc)
    ids: list[str] = []
    for i in range(5):
        cmd = await _make_command(
            test_db, host=host, issued_at=base - timedelta(minutes=i)
        )
        ids.append(str(cmd.id))
    # Newest first: ids[0] is most recent (issued at base - 0)
    _override_user(admin)
    try:
        page1 = (await client.get("/v1/dash/commands?limit=2")).json()
        assert len(page1["commands"]) == 2
        assert page1["next_cursor"] is not None
        page2 = (
            await client.get(
                f"/v1/dash/commands?limit=2&cursor={page1['next_cursor']}"
            )
        ).json()
        assert len(page2["commands"]) == 2
        assert page2["next_cursor"] is not None
        page3 = (
            await client.get(
                f"/v1/dash/commands?limit=2&cursor={page2['next_cursor']}"
            )
        ).json()
        assert len(page3["commands"]) == 1
        assert page3["next_cursor"] is None
    finally:
        _clear_user_override()

    collected = [c["id"] for c in page1["commands"] + page2["commands"] + page3["commands"]]
    assert collected == ids  # newest-first ordering preserved


@pytest.mark.asyncio
async def test_commands_list_filters_status_and_host(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """``?status=`` and ``?host_id=`` narrow the result set."""
    admin = await _make_user(test_db, role="admin")
    h1 = await _make_host(test_db, hostname="h1", group="prod")
    h2 = await _make_host(test_db, hostname="h2", group="prod")
    await _make_command(test_db, host=h1, completed_at=datetime.now(timezone.utc), exit_code=0)
    await _make_command(test_db, host=h1, completed_at=datetime.now(timezone.utc), exit_code=1)
    await _make_command(test_db, host=h2)
    _override_user(admin)
    try:
        ok = (await client.get("/v1/dash/commands?status=succeeded")).json()
        assert len(ok["commands"]) == 1
        assert ok["commands"][0]["status"] == "succeeded"

        failed = (await client.get("/v1/dash/commands?status=failed")).json()
        assert len(failed["commands"]) == 1
        assert failed["commands"][0]["status"] == "failed"

        by_host = (await client.get(f"/v1/dash/commands?host_id={h2.id}")).json()
        assert len(by_host["commands"]) == 1
        assert by_host["commands"][0]["host_hostname"] == "h2"

        by_issuer = (
            await client.get("/v1/dash/commands?issued_by=ops@test.local")
        ).json()
        assert len(by_issuer["commands"]) == 3
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_commands_list_rejects_bad_cursor(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/commands?cursor=not-base64!!!")
    finally:
        _clear_user_override()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_commands_list_viewer_acl(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Viewer with ``accessible_groups=['family']`` cannot see prod commands."""
    viewer = await _make_user(test_db, role="viewer", groups=["family"])
    prod_host = await _make_host(test_db, hostname="prod-h", group="prod")
    fam_host = await _make_host(test_db, hostname="fam-h", group="family")
    await _make_command(test_db, host=prod_host)
    await _make_command(test_db, host=fam_host)
    _override_user(viewer)
    try:
        resp = await client.get("/v1/dash/commands")
    finally:
        _clear_user_override()

    body = resp.json()
    assert len(body["commands"]) == 1
    assert body["commands"][0]["host_hostname"] == "fam-h"


# --------------------------------------------------------------------------- #
# POST /v1/dash/commands — issuance
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue_creates_one_command_per_host(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """``host_ids`` of N → N command rows returned + persisted."""
    admin = await _make_user(test_db, role="admin")
    h1 = await _make_host(test_db, hostname="h-issue-1", group="prod")
    h2 = await _make_host(test_db, hostname="h-issue-2", group="prod")
    _override_user(admin)
    try:
        resp = await client.post(
            "/v1/dash/commands",
            json={
                "host_ids": [str(h1.id), str(h2.id)],
                "command_type": "apt_update",
                "command_payload": {"packages": ["curl"]},
                "requires_approval": False,
            },
        )
    finally:
        _clear_user_override()
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["commands"]) == 2
    statuses = {c["host_hostname"]: c["status"] for c in body["commands"]}
    # No approval required → "queued"
    assert statuses == {"h-issue-1": "queued", "h-issue-2": "queued"}


@pytest.mark.asyncio
async def test_issue_honours_requires_approval(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """``requires_approval=True`` parks the command in pending-approval."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="hh", group="prod")
    _override_user(admin)
    try:
        resp = await client.post(
            "/v1/dash/commands",
            json={
                "host_ids": [str(host.id)],
                "command_type": "reboot",
                "command_payload": {},
                # requires_approval omitted → default policy kicks in (reboot is destructive)
            },
        )
    finally:
        _clear_user_override()
    assert resp.status_code == 201
    cmd = resp.json()["commands"][0]
    assert cmd["status"] == "pending-approval"
    assert cmd["human_approved"] is False
    assert cmd["approval_requested_at"] is not None


@pytest.mark.asyncio
async def test_issue_rejects_unknown_host(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        resp = await client.post(
            "/v1/dash/commands",
            json={
                "host_ids": [str(uuid.uuid4())],
                "command_type": "shell",
                "command_payload": {"cmd": "true"},
                "requires_approval": False,
            },
        )
    finally:
        _clear_user_override()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_issue_viewer_forbidden(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Viewer cannot issue (operator+ required)."""
    viewer = await _make_user(test_db, role="viewer", groups=["prod"])
    host = await _make_host(test_db, hostname="hh", group="prod")
    _override_user(viewer)
    try:
        resp = await client.post(
            "/v1/dash/commands",
            json={
                "host_ids": [str(host.id)],
                "command_type": "shell",
                "command_payload": {"cmd": "true"},
                "requires_approval": False,
            },
        )
    finally:
        _clear_user_override()
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# POST /v1/dash/commands/{id}/retry
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_retry_creates_new_command_same_payload(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="retry-h", group="prod")
    orig = await _make_command(
        test_db,
        host=host,
        command_type="apt_update",
        payload={"packages": ["nginx"]},
        completed_at=datetime.now(timezone.utc),
        exit_code=1,
    )
    _override_user(admin)
    try:
        resp = await client.post(f"/v1/dash/commands/{orig.id}/retry")
    finally:
        _clear_user_override()
    assert resp.status_code == 201
    new = resp.json()
    assert new["id"] != str(orig.id)
    assert new["command_type"] == "apt_update"
    # payload preserved (the retry handler adds a 'reason' field on top)
    assert new["command_payload"].get("packages") == ["nginx"]
    assert new["host_id"] == str(host.id)


# --------------------------------------------------------------------------- #
# Approvals — approve / reject / pending
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pending_approvals_visible_only_to_acl(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """A viewer's pending list excludes other groups' approvals."""
    viewer = await _make_user(test_db, role="viewer", groups=["family"])
    prod_host = await _make_host(test_db, hostname="prod-h", group="prod")
    fam_host = await _make_host(test_db, hostname="fam-h", group="family")
    now = datetime.now(timezone.utc)
    await _make_command(
        test_db,
        host=prod_host,
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=now,
    )
    await _make_command(
        test_db,
        host=fam_host,
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=now,
    )
    _override_user(viewer)
    try:
        resp = await client.get("/v1/dash/approvals/pending")
    finally:
        _clear_user_override()
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["host_hostname"] == "fam-h"


@pytest.mark.asyncio
async def test_approve_marks_command_and_emits_event(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """approve → human_approved=true + SSE approval.resolved."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="appr-h", group="prod")
    pending = await _make_command(
        test_db,
        host=host,
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=datetime.now(timezone.utc),
    )

    received: list[tuple[str, dict[str, Any]]] = []

    async def consume() -> None:
        async for ev_type, payload in event_bus.subscribe():
            received.append((ev_type, payload))
            if any(t == "approval.resolved" for t, _ in received):
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    _override_user(admin)
    try:
        resp = await client.post(
            f"/v1/dash/approvals/{pending.id}/approve", json={"reason": "lgtm"}
        )
    finally:
        _clear_user_override()

    await asyncio.wait_for(task, timeout=2.0)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["command_id"] == str(pending.id)
    resolved = [p for t, p in received if t == "approval.resolved"]
    assert resolved
    assert resolved[0]["resolution"] == "approved"
    assert resolved[0]["resolved_by"] == admin.email


@pytest.mark.asyncio
async def test_reject_marks_command_and_emits_event(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="rej-h", group="prod")
    pending = await _make_command(
        test_db,
        host=host,
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=datetime.now(timezone.utc),
    )

    received: list[tuple[str, dict[str, Any]]] = []

    async def consume() -> None:
        async for ev_type, payload in event_bus.subscribe():
            received.append((ev_type, payload))
            if any(t == "approval.resolved" for t, _ in received):
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    _override_user(admin)
    try:
        resp = await client.post(
            f"/v1/dash/approvals/{pending.id}/reject", json={"reason": "too risky"}
        )
    finally:
        _clear_user_override()

    await asyncio.wait_for(task, timeout=2.0)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    resolved = [p for t, p in received if t == "approval.resolved"]
    assert resolved
    assert resolved[0]["resolution"] == "rejected"
    assert resolved[0]["reason"] == "too risky"


@pytest.mark.asyncio
async def test_approve_twice_is_conflict(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="dup-h", group="prod")
    pending = await _make_command(
        test_db,
        host=host,
        human_approved=False,
        approval_token=uuid.uuid4(),
        approval_requested_at=datetime.now(timezone.utc),
    )
    _override_user(admin)
    try:
        first = await client.post(f"/v1/dash/approvals/{pending.id}/approve", json={})
        assert first.status_code == 200
        second = await client.post(f"/v1/dash/approvals/{pending.id}/approve", json={})
    finally:
        _clear_user_override()
    assert second.status_code == 409


# --------------------------------------------------------------------------- #
# SSE: issue → command.issued event
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue_emits_command_issued_event(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="emit-h", group="prod")

    received: list[tuple[str, dict[str, Any]]] = []

    async def consume() -> None:
        async for ev_type, payload in event_bus.subscribe():
            received.append((ev_type, payload))
            if any(t == "command.issued" for t, _ in received):
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    _override_user(admin)
    try:
        resp = await client.post(
            "/v1/dash/commands",
            json={
                "host_ids": [str(host.id)],
                "command_type": "apt_update",
                "command_payload": {},
                "requires_approval": False,
            },
        )
    finally:
        _clear_user_override()

    await asyncio.wait_for(task, timeout=2.0)
    assert resp.status_code == 201
    issued = [p for t, p in received if t == "command.issued"]
    assert issued
    assert issued[0]["host_id"] == str(host.id)
    assert issued[0]["command_type"] == "apt_update"
    assert issued[0]["group_name"] == "prod"


# --------------------------------------------------------------------------- #
# /v1/dash/audit
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_audit_covers_all_sources(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Synthesised timeline includes events from every source table."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="audit-host", group="prod")
    now = datetime.now(timezone.utc)
    # command.issued + command.completed (success)
    await _make_command(
        test_db,
        host=host,
        issued_at=now - timedelta(minutes=5),
        completed_at=now - timedelta(minutes=4),
        exit_code=0,
    )
    # command.failed
    await _make_command(
        test_db,
        host=host,
        issued_at=now - timedelta(minutes=3),
        completed_at=now - timedelta(minutes=2),
        exit_code=2,
    )
    # command.approved
    await _make_command(
        test_db,
        host=host,
        issued_at=now - timedelta(minutes=10),
        human_approved=True,
        approved_by="someone@x",
        approval_responded_at=now - timedelta(minutes=9),
    )
    # command.rejected
    await _make_command(
        test_db,
        host=host,
        issued_at=now - timedelta(minutes=11),
        human_approved=False,
        rejected_reason="dash:x:nope",
        approval_responded_at=now - timedelta(minutes=10, seconds=30),
    )
    # enrollment.token_issued
    enrollment = Enrollment(
        token_jti="jti-test",
        issued_by="admin@test.local",
        group_name="prod",
        expires_at=now + timedelta(hours=1),
        max_uses=1,
        used_count=0,
    )
    test_db.add(enrollment)
    await test_db.commit()

    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit?limit=50")
    finally:
        _clear_user_override()
    assert resp.status_code == 200
    body = resp.json()
    actions = {e["action"] for e in body["events"]}
    # host.enrolled comes from Host.enrolled_at (set in _make_host)
    assert "host.enrolled" in actions
    assert "command.issued" in actions
    assert "command.completed" in actions
    assert "command.failed" in actions
    assert "command.approved" in actions
    assert "command.rejected" in actions
    assert "enrollment.token_issued" in actions


@pytest.mark.asyncio
async def test_audit_filters_action_and_actor(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="filt-host", group="prod")
    await _make_command(test_db, host=host, issued_by="alice@x")
    await _make_command(test_db, host=host, issued_by="bob@x")
    _override_user(admin)
    try:
        only_issued = (
            await client.get("/v1/dash/audit?action=command.issued")
        ).json()
        actions = {e["action"] for e in only_issued["events"]}
        assert actions == {"command.issued"}
        assert len(only_issued["events"]) == 2

        by_actor = (
            await client.get("/v1/dash/audit?action=command.issued&actor=alice@x")
        ).json()
        assert len(by_actor["events"]) == 1
        assert by_actor["events"][0]["actor"] == "alice@x"
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_audit_cursor_pagination(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Walking the cursor yields each event exactly once."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="cur-host", group="prod")
    base = datetime.now(timezone.utc)
    for i in range(6):
        await _make_command(test_db, host=host, issued_at=base - timedelta(minutes=i))
    _override_user(admin)
    try:
        page1 = (
            await client.get("/v1/dash/audit?action=command.issued&limit=3")
        ).json()
        assert len(page1["events"]) == 3
        assert page1["next_cursor"] is not None
        page2 = (
            await client.get(
                f"/v1/dash/audit?action=command.issued&limit=3"
                f"&cursor={page1['next_cursor']}"
            )
        ).json()
        assert len(page2["events"]) == 3
        assert page2["next_cursor"] is None
    finally:
        _clear_user_override()

    ids = [e["id"] for e in page1["events"] + page2["events"]]
    assert len(set(ids)) == 6  # no duplicates


@pytest.mark.asyncio
async def test_audit_viewer_acl_drops_other_groups(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """A viewer in 'family' must not see prod commands in the audit feed."""
    viewer = await _make_user(test_db, role="viewer", groups=["family"])
    prod_host = await _make_host(test_db, hostname="p-h", group="prod")
    fam_host = await _make_host(test_db, hostname="f-h", group="family")
    await _make_command(test_db, host=prod_host)
    await _make_command(test_db, host=fam_host)
    _override_user(viewer)
    try:
        resp = await client.get("/v1/dash/audit?action=command.issued")
    finally:
        _clear_user_override()
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["target_label"].endswith("f-h")


@pytest.mark.asyncio
async def test_audit_rejects_unknown_action(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit?action=does.not.exist")
    finally:
        _clear_user_override()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_audit_target_type_filter(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="tgt-host", group="prod")
    await _make_command(test_db, host=host)
    _override_user(admin)
    try:
        only_hosts = (await client.get("/v1/dash/audit?target_type=host")).json()
    finally:
        _clear_user_override()
    actions = {e["action"] for e in only_hosts["events"]}
    # Only host.* survives target_type=host
    assert actions <= {"host.enrolled"}
