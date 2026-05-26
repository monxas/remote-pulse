"""Tests for the refined ``/v1/dash/audit`` filters + offset pagination.

Covers the additions made in feat/audit-filters-export:

- ``action_prefix`` (mutually exclusive with ``action``).
- ``actor`` case-insensitive matching.
- ``resource_type`` alias of ``target_type``.
- ``from_ts`` / ``to_ts`` alias of ``since`` / ``until``.
- Offset-mode pagination + ``total`` / ``has_more`` envelope.
- Validation: ``from_ts >= to_ts`` → 422.
- Validation: ``action`` + ``action_prefix`` together → 422.
- Validation: ``cursor`` + ``offset`` together → 422.

The fixtures are reused from ``test_dash_phase2.py`` via direct imports.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import AuditEvent as AuditEventRow
from rp_server.models import Enrollment, User
from rp_server.routers import commands as commands_router
from rp_server.routers import dash_commands as dash_commands_router

from tests.test_dash_phase2 import (
    _clear_user_override,
    _make_command,
    _make_host,
    _make_user,
    _override_user,
)


@pytest.fixture(autouse=True)
def _patch_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same stub as test_dash_phase2 — avoid touching /etc/rp."""

    class _FakeKey:
        def sign_command(self, *a, **kw):
            return "sig-stub"

        def public_key_pem(self) -> bytes:
            return b"-----BEGIN PUBLIC KEY-----\nstub\n-----END PUBLIC KEY-----\n"

    monkeypatch.setattr(commands_router, "get_signing_key", lambda: _FakeKey())
    monkeypatch.setattr(dash_commands_router, "get_signing_key", lambda: _FakeKey())


async def _seed_settings_event(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    ts: datetime | None = None,
    payload: dict | None = None,
) -> AuditEventRow:
    row = AuditEventRow(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {"name": resource_id},
    )
    if ts is not None:
        row.ts = ts
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# actor case-insensitive
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_actor_filter_is_case_insensitive(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="ci-host", group="prod")
    await _make_command(test_db, host=host, issued_by="Alice@Example.com")
    _override_user(admin)
    try:
        upper = (await client.get("/v1/dash/audit?actor=ALICE@example.com")).json()
        lower = (await client.get("/v1/dash/audit?actor=alice@example.com")).json()
        mixed = (await client.get("/v1/dash/audit?actor=Alice@Example.com")).json()
    finally:
        _clear_user_override()
    # All three queries must return the same set of events.
    assert len(upper["events"]) == len(lower["events"]) == len(mixed["events"])
    assert len(upper["events"]) >= 1
    for e in upper["events"]:
        assert e["actor"].lower() == "alice@example.com"


# --------------------------------------------------------------------------- #
# action_prefix
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_action_prefix_settings_dot(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """``action_prefix=settings.`` should match all settings.* events only."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="pfx-host", group="prod")
    await _make_command(test_db, host=host)  # command.issued — must NOT match
    await _seed_settings_event(
        test_db,
        actor=admin.email,
        action="settings.group.create",
        resource_type="group",
        resource_id="alpha",
    )
    await _seed_settings_event(
        test_db,
        actor=admin.email,
        action="settings.user.update",
        resource_type="user",
        resource_id="u-1",
    )
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit?action_prefix=settings.")
    finally:
        _clear_user_override()
    body = resp.json()
    actions = {e["action"] for e in body["events"]}
    assert actions == {"settings.group.create", "settings.user.update"}
    assert all(a.startswith("settings.") for a in actions)


@pytest.mark.asyncio
async def test_action_prefix_command_dot(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="pfxc-host", group="prod")
    await _make_command(test_db, host=host)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit?action_prefix=command.")
    finally:
        _clear_user_override()
    body = resp.json()
    actions = {e["action"] for e in body["events"]}
    assert actions  # at least command.issued
    assert all(a.startswith("command.") for a in actions)


@pytest.mark.asyncio
async def test_action_and_action_prefix_is_422(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        resp = await client.get(
            "/v1/dash/audit?action=command.issued&action_prefix=command."
        )
    finally:
        _clear_user_override()
    assert resp.status_code == 422
    assert "mutually exclusive" in resp.text


# --------------------------------------------------------------------------- #
# resource_type alias of target_type
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resource_type_alias(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="rt-host", group="prod")
    await _make_command(test_db, host=host)
    _override_user(admin)
    try:
        a = (await client.get("/v1/dash/audit?target_type=command")).json()
        b = (await client.get("/v1/dash/audit?resource_type=command")).json()
    finally:
        _clear_user_override()
    assert {e["id"] for e in a["events"]} == {e["id"] for e in b["events"]}


# --------------------------------------------------------------------------- #
# Date range
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_date_range_from_ts_to_ts(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="dr-host", group="prod")
    base = datetime.now(timezone.utc).replace(microsecond=0)
    # Three commands across a known timeline.
    await _make_command(test_db, host=host, issued_at=base - timedelta(hours=3))
    await _make_command(test_db, host=host, issued_at=base - timedelta(hours=2))
    await _make_command(test_db, host=host, issued_at=base - timedelta(hours=1))

    from_ts = (base - timedelta(hours=2, minutes=30)).isoformat().replace("+00:00", "Z")
    to_ts = (base - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    _override_user(admin)
    try:
        resp = await client.get(
            f"/v1/dash/audit?action=command.issued&from_ts={from_ts}&to_ts={to_ts}"
        )
    finally:
        _clear_user_override()
    body = resp.json()
    # Only the two events inside the window should match
    assert len(body["events"]) == 2


@pytest.mark.asyncio
async def test_from_ts_not_less_than_to_ts_is_422(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    earlier = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    try:
        # from_ts == to_ts -> 422
        r1 = await client.get(f"/v1/dash/audit?from_ts={now}&to_ts={now}")
        # from_ts > to_ts  -> 422
        r2 = await client.get(f"/v1/dash/audit?from_ts={now}&to_ts={earlier}")
    finally:
        _clear_user_override()
    assert r1.status_code == 422
    assert r2.status_code == 422


# --------------------------------------------------------------------------- #
# Combined filters
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_combined_actor_action_date(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="combo-host", group="prod")
    base = datetime.now(timezone.utc).replace(microsecond=0)
    await _make_command(
        test_db, host=host, issued_by="alice@x", issued_at=base - timedelta(hours=2)
    )
    await _make_command(
        test_db, host=host, issued_by="alice@x", issued_at=base - timedelta(days=10)
    )
    await _make_command(
        test_db, host=host, issued_by="bob@x", issued_at=base - timedelta(hours=2)
    )

    since = (base - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    _override_user(admin)
    try:
        resp = await client.get(
            f"/v1/dash/audit?action=command.issued&actor=ALICE@x&from_ts={since}"
        )
    finally:
        _clear_user_override()
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["actor"] == "alice@x"


# --------------------------------------------------------------------------- #
# Offset pagination + total + has_more
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_offset_pagination_and_total(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="off-host", group="prod")
    base = datetime.now(timezone.utc)
    for i in range(7):
        await _make_command(test_db, host=host, issued_at=base - timedelta(minutes=i))
    _override_user(admin)
    try:
        first = (
            await client.get("/v1/dash/audit?action=command.issued&limit=3&offset=0")
        ).json()
        second = (
            await client.get("/v1/dash/audit?action=command.issued&limit=3&offset=3")
        ).json()
        third = (
            await client.get("/v1/dash/audit?action=command.issued&limit=3&offset=6")
        ).json()
    finally:
        _clear_user_override()

    assert first["total"] == 7
    assert second["total"] == 7
    assert third["total"] == 7
    assert first["limit"] == 3
    assert first["offset"] == 0
    assert second["offset"] == 3
    assert len(first["events"]) == 3
    assert len(second["events"]) == 3
    assert len(third["events"]) == 1
    assert first["has_more"] is True
    assert second["has_more"] is True
    assert third["has_more"] is False
    # No duplicate ids across the pages
    ids = (
        [e["id"] for e in first["events"]]
        + [e["id"] for e in second["events"]]
        + [e["id"] for e in third["events"]]
    )
    assert len(set(ids)) == 7


@pytest.mark.asyncio
async def test_offset_and_cursor_together_is_422(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit?offset=0&cursor=abc")
    finally:
        _clear_user_override()
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_response_envelope_always_includes_total(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Even the cursor-mode response should carry total/limit/offset/has_more."""
    admin = await _make_user(test_db, role="admin")
    host = await _make_host(test_db, hostname="env-host", group="prod")
    await _make_command(test_db, host=host)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/audit?limit=10")
    finally:
        _clear_user_override()
    body = resp.json()
    for key in ("events", "total", "limit", "offset", "has_more", "next_cursor"):
        assert key in body, f"missing key: {key}"
    assert body["total"] >= 1
    assert body["offset"] == 0
