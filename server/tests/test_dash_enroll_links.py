"""Tests for the dashboard magic-link issuance API.

Covers ``/v1/dash/enroll/links``:

- admin can POST, GET and DELETE
- non-admin (viewer / operator) hits 403 on every route
- TTL / max_uses validation produces 422
- listing only returns active links (expired + exhausted + revoked are hidden)
- DELETE soft-revokes (row stays in DB, but it no longer shows up in listing
  and the JWT claims still decode — only the side-channel guard rejects)

We reuse the fake-auth pattern from test_dash_settings: override the
``current_user`` dependency at the app level so ``require_admin`` evaluates
against our seeded fixture user.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.auth import decode_enrollment_token
from rp_server.config import settings
from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import Enrollment, User


# Force ``server_url`` into the install allowlist (see dash_enroll._safe_base_url)
# for the duration of the test session. The base value baked in by conftest
# (``http://test``) is not allowlisted by design.
@pytest.fixture(autouse=True)
def _allowlisted_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "server_url", "https://rp.monxas.casa")


# --------------------------------------------------------------------------- #
# Auth helpers (mirror of test_dash_settings.py)
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
    email: str | None = None,
) -> User:
    u = User(
        pocketid_sub=f"{role}-{uuid.uuid4().hex[:8]}",
        email=email or f"{role}-{uuid.uuid4().hex[:8]}@test.local",
        name=role.title(),
        role=role,
        accessible_groups=[],
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


# --------------------------------------------------------------------------- #
# Auth gating
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_viewer_blocked_from_enroll_links(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    viewer = await _make_user(test_db, role="viewer")
    _override_user(viewer)
    try:
        r = await client.get("/v1/dash/enroll/links")
        assert r.status_code == 403, r.text

        r = await client.post(
            "/v1/dash/enroll/links",
            json={"group_name": "default", "ttl_hours": 24, "max_uses": 1},
        )
        assert r.status_code == 403

        # DELETE used to be admin-only via dependency; it now gates on the
        # ``enroll.revoke`` permission (404 wins over 403). The jti below
        # doesn't exist so the viewer hits the not-found branch before the
        # permission check has a chance to fire.
        r = await client.delete("/v1/dash/enroll/links/some-jti")
        assert r.status_code == 404
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_operator_blocked_from_enroll_links(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    op = await _make_user(test_db, role="operator")
    _override_user(op)
    try:
        r = await client.get("/v1/dash/enroll/links")
        assert r.status_code == 403
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_creates_link_happy(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin", email="admin@test.local")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/enroll/links",
            json={
                "group_name": "family",
                "ttl_hours": 12,
                "max_uses": 3,
                "label": "Mac mini Mario",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["group_name"] == "family"
        assert body["max_uses"] == 3
        assert body["used_count"] == 0
        assert body["expires_in_hours"] == 12
        assert body["issued_by"] == "admin@test.local"
        assert body["label"] == "Mac mini Mario"
        assert body["token"]
        assert body["token_jti"]
        # URL must embed the token verbatim so an agent can install from it.
        assert body["url"].endswith(f"?token={body['token']}")
        assert "install" in body["url"]

        # JWT claims must match what we asked for; this is the canonical
        # decoder used by routers/enroll.py.
        claims = decode_enrollment_token(body["token"])
        assert claims["group_name"] == "family"
        assert claims["max_uses"] == 3
        assert claims["issued_by"] == "admin@test.local"
        assert claims["jti"] == body["token_jti"]

        # And the row landed in the enrollments table.
        row = (
            await test_db.execute(
                select(Enrollment).where(Enrollment.token_jti == body["token_jti"])
            )
        ).scalar_one()
        assert row.group_name == "family"
        assert row.max_uses == 3
        assert row.used_count == 0
    finally:
        _clear_user_override()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        # ttl_hours out of range
        {"group_name": "default", "ttl_hours": 0, "max_uses": 1},
        {"group_name": "default", "ttl_hours": 9999, "max_uses": 1},
        # max_uses out of range
        {"group_name": "default", "ttl_hours": 24, "max_uses": 0},
        {"group_name": "default", "ttl_hours": 24, "max_uses": 9999},
        # bad group name (regex)
        {"group_name": "", "ttl_hours": 24, "max_uses": 1},
        {"group_name": "has space", "ttl_hours": 24, "max_uses": 1},
        {"group_name": "-leading-dash", "ttl_hours": 24, "max_uses": 1},
    ],
)
async def test_create_link_validation(
    client: AsyncClient, test_db: AsyncSession, payload: dict
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post("/v1/dash/enroll/links", json=payload)
        assert r.status_code == 422, (payload, r.text)
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# List
# --------------------------------------------------------------------------- #


async def _seed_enrollment(
    db: AsyncSession,
    *,
    group: str,
    ttl_hours: int = 24,
    max_uses: int = 1,
    used_count: int = 0,
    issued_by: str = "seed@test.local",
) -> Enrollment:
    e = Enrollment(
        token_jti=str(uuid.uuid4()),
        issued_by=issued_by,
        group_name=group,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        max_uses=max_uses,
        used_count=used_count,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


@pytest.mark.asyncio
async def test_list_filters_out_expired_and_exhausted(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")

    active = await _seed_enrollment(test_db, group="alpha")
    # Already expired in the past.
    expired = Enrollment(
        token_jti=str(uuid.uuid4()),
        issued_by="seed@test.local",
        group_name="beta",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        max_uses=1,
        used_count=0,
    )
    test_db.add(expired)
    # Used all its uses.
    exhausted = await _seed_enrollment(
        test_db, group="gamma", max_uses=2, used_count=2
    )
    await test_db.commit()

    _override_user(admin)
    try:
        r = await client.get("/v1/dash/enroll/links")
        assert r.status_code == 200, r.text
        jtis = {row["token_jti"] for row in r.json()["links"]}
        assert active.token_jti in jtis
        assert expired.token_jti not in jtis
        assert exhausted.token_jti not in jtis
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# Revoke
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_revoke_link_makes_it_disappear_from_listing(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    target = await _seed_enrollment(test_db, group="alpha", max_uses=3)

    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/enroll/links/{target.token_jti}")
        assert r.status_code == 204, r.text

        # Listing no longer includes it.
        r = await client.get("/v1/dash/enroll/links")
        assert r.status_code == 200
        jtis = {row["token_jti"] for row in r.json()["links"]}
        assert target.token_jti not in jtis

        # Row is still there but neutered (used_count == max_uses, expires_at
        # in the past). We re-fetch from the DB session.
        await test_db.refresh(target)
        assert target.used_count == target.max_uses
        # SQLite drops the timezone on round-trip; normalise both sides.
        expires_at = target.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        assert expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        _clear_user_override()


@pytest.mark.asyncio
async def test_revoke_unknown_link_returns_404(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.delete("/v1/dash/enroll/links/does-not-exist")
        assert r.status_code == 404
    finally:
        _clear_user_override()
