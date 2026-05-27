"""Tests for the audit retention subsystem.

Covers:

* singleton config defaulting + bounds
* the purge query honouring ``enabled`` and the time cutoff
* book-keeping (``last_purge_at`` / ``last_purge_count``) after a run
* admin-only gating on the three HTTP endpoints
* validation of ``retention_days`` bounds at the API layer
* audit-row emission on PATCH + purge-now
* edge: zero rows to purge returns ``0`` without exploding
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.audit_retention import (
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    get_config,
    purge_old_audit_events,
    update_config,
)
from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import AuditEvent, AuditRetentionConfig, User


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    async def _fake() -> User:
        return user

    app.dependency_overrides[current_user] = _fake


def _clear_override() -> None:
    app.dependency_overrides.pop(current_user, None)


async def _make_user(db: AsyncSession, *, role: str = "admin") -> User:
    u = User(
        pocketid_sub=f"{role}-{uuid.uuid4().hex[:8]}",
        email=f"{role}-{uuid.uuid4().hex[:6]}@test.local",
        name=role.title(),
        role=role,
        accessible_groups=[],
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _seed_audit_event(
    db: AsyncSession,
    *,
    ts: datetime,
    action: str = "test.event",
) -> AuditEvent:
    """Insert an audit event with an explicit timestamp.

    The model has a server_default of ``now()``; in the SQLite test
    fixture that's replaced by a Python ColumnDefault, which is only
    applied when ``ts`` isn't set explicitly. Setting it here gives us
    control over the time-axis for purge tests.
    """
    ev = AuditEvent(
        ts=ts,
        actor="seed",
        action=action,
        resource_type="test",
        resource_id="r",
        payload={},
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev


# --------------------------------------------------------------------------- #
# Service-layer
# --------------------------------------------------------------------------- #


async def test_get_config_seeds_default_when_missing(test_db: AsyncSession) -> None:
    """If the singleton row is absent, ``get_config`` creates it."""
    # SQLite create_all doesn't seed the row (no INSERT in CREATE), so
    # this matches the production "fresh DB before migration" path.
    config = await get_config(test_db)
    assert config.id == 1
    assert config.retention_days == 90
    assert config.enabled is True
    assert config.updated_by == "system"


async def test_update_config_persists_and_rejects_out_of_range(
    test_db: AsyncSession,
) -> None:
    await get_config(test_db)

    row = await update_config(test_db, actor="admin@test", retention_days=30)
    assert row.retention_days == 30
    assert row.updated_by == "admin@test"

    row = await update_config(test_db, actor="admin@test", enabled=False)
    assert row.enabled is False
    assert row.retention_days == 30  # untouched

    with pytest.raises(ValueError):
        await update_config(test_db, actor="x", retention_days=MIN_RETENTION_DAYS - 1)
    with pytest.raises(ValueError):
        await update_config(test_db, actor="x", retention_days=MAX_RETENTION_DAYS + 1)


async def test_purge_deletes_only_old_rows(test_db: AsyncSession) -> None:
    """Rows older than retention_days vanish; newer rows survive."""
    now = datetime.now(timezone.utc)
    await get_config(test_db)
    await update_config(test_db, actor="t", retention_days=30)
    await test_db.commit()

    old = await _seed_audit_event(test_db, ts=now - timedelta(days=60))
    fresh = await _seed_audit_event(test_db, ts=now - timedelta(days=1))

    deleted = await purge_old_audit_events(test_db, now=now)
    assert deleted == 1

    remaining = (await test_db.execute(select(AuditEvent.id))).scalars().all()
    assert old.id not in remaining
    assert fresh.id in remaining


async def test_purge_respects_enabled_false(test_db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await get_config(test_db)
    await update_config(test_db, actor="t", retention_days=30, enabled=False)
    await test_db.commit()

    await _seed_audit_event(test_db, ts=now - timedelta(days=60))

    deleted = await purge_old_audit_events(test_db, now=now)
    assert deleted == 0

    # The old row should still be there — disabled means "do nothing".
    rows = (await test_db.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1


async def test_purge_updates_book_keeping(test_db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await get_config(test_db)
    await update_config(test_db, actor="t", retention_days=10)
    await test_db.commit()

    for offset in (20, 30, 40):
        await _seed_audit_event(test_db, ts=now - timedelta(days=offset))

    deleted = await purge_old_audit_events(test_db, now=now)
    assert deleted == 3

    config = (
        await test_db.execute(select(AuditRetentionConfig).where(AuditRetentionConfig.id == 1))
    ).scalar_one()
    assert config.last_purge_count == 3
    assert config.last_purge_at is not None


async def test_purge_with_no_old_events_is_a_noop(test_db: AsyncSession) -> None:
    """Edge: empty / all-fresh table — still updates last_purge_at."""
    now = datetime.now(timezone.utc)
    await get_config(test_db)
    await test_db.commit()

    await _seed_audit_event(test_db, ts=now - timedelta(days=1))

    deleted = await purge_old_audit_events(test_db, now=now)
    assert deleted == 0

    config = (
        await test_db.execute(select(AuditRetentionConfig).where(AuditRetentionConfig.id == 1))
    ).scalar_one()
    assert config.last_purge_count == 0
    assert config.last_purge_at is not None


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #


async def test_get_retention_admin_only(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    viewer = await _make_user(test_db, role="viewer")
    _override_user(viewer)
    try:
        r = await client.get("/v1/dash/settings/retention")
        assert r.status_code == 403
    finally:
        _clear_override()


async def test_get_retention_returns_defaults(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.get("/v1/dash/settings/retention")
        assert r.status_code == 200
        body = r.json()
        assert body["retention_days"] == 90
        assert body["enabled"] is True
        assert body["min_days"] == MIN_RETENTION_DAYS
        assert body["max_days"] == MAX_RETENTION_DAYS
        assert body["last_purge_at"] is None
    finally:
        _clear_override()


async def test_patch_retention_validates_bounds(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        # Below floor
        r = await client.patch(
            "/v1/dash/settings/retention",
            json={"retention_days": MIN_RETENTION_DAYS - 1},
        )
        assert r.status_code == 422

        # Above ceiling
        r = await client.patch(
            "/v1/dash/settings/retention",
            json={"retention_days": MAX_RETENTION_DAYS + 1},
        )
        assert r.status_code == 422

        # Empty body — neither field => 400
        r = await client.patch("/v1/dash/settings/retention", json={})
        assert r.status_code == 400
    finally:
        _clear_override()


async def test_patch_retention_persists_and_emits_audit(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.patch(
            "/v1/dash/settings/retention",
            json={"retention_days": 45, "enabled": False},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["retention_days"] == 45
        assert body["enabled"] is False
        assert body["updated_by"] == admin.email

        # Audit row exists for the change.
        rows = (
            await test_db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "audit.retention.config_updated"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor == admin.email
        assert "changes" in rows[0].payload
    finally:
        _clear_override()


async def test_patch_retention_non_admin_forbidden(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    op = await _make_user(test_db, role="operator")
    _override_user(op)
    try:
        r = await client.patch(
            "/v1/dash/settings/retention",
            json={"retention_days": 30},
        )
        assert r.status_code == 403
    finally:
        _clear_override()


async def test_purge_now_admin_only(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    viewer = await _make_user(test_db, role="viewer")
    _override_user(viewer)
    try:
        r = await client.post("/v1/dash/settings/retention/purge-now")
        assert r.status_code == 403
    finally:
        _clear_override()


async def test_purge_now_runs_and_emits_audit(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    admin = await _make_user(test_db, role="admin")
    now = datetime.now(timezone.utc)

    # Seed: shorten policy so the test event qualifies for purge.
    await get_config(test_db)
    await update_config(test_db, actor="t", retention_days=10)
    await test_db.commit()
    await _seed_audit_event(test_db, ts=now - timedelta(days=60))

    _override_user(admin)
    try:
        r = await client.post("/v1/dash/settings/retention/purge-now")
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 1
        assert body["retention_days"] == 10
        assert body["enabled"] is True

        # An audit row for the manual trigger must survive (it was
        # committed before the purge ran, so it's not in the deleted
        # set even if its timestamp were ancient).
        rows = (
            await test_db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "audit.retention.manual_purge"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor == admin.email
    finally:
        _clear_override()
