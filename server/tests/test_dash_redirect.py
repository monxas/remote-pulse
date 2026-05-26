"""Tests for the ADR-0009 Phase 3 ``/dash/*`` -> ``/dash-next/*`` cutover.

These tests pin down two behaviours of ``rp_server.routers.dash_redirect``:

1. Legacy Jinja paths return a ``302`` whose ``Location`` points to the
   SPA equivalent under ``/dash-next/``. Path *and* query string are
   preserved.
2. The one preserved endpoint — ``/dash/host/{host_id}/sparkline-data`` —
   keeps working end-to-end (i.e. is not swallowed by the catch-all
   redirect).

Auth uses the same ``dependency_overrides`` pattern as the other dash
tests in this suite (``test_dash_api.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import Host, User


# --------------------------------------------------------------------------- #
# Helpers (mirrors test_dash_api.py — kept local to avoid cross-test imports)
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    async def _fake_current_user() -> User:
        return user

    app.dependency_overrides[current_user] = _fake_current_user


def _clear_user_override() -> None:
    app.dependency_overrides.pop(current_user, None)


async def _make_admin(db: AsyncSession) -> User:
    user = User(
        pocketid_sub=f"admin-{uuid.uuid4().hex[:8]}",
        email=f"admin-{uuid.uuid4().hex[:8]}@test.local",
        name="Admin",
        role="admin",
        accessible_groups=[],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_host(db: AsyncSession, *, hostname: str, group: str = "prod") -> Host:
    host = Host(
        hostname=hostname,
        os="linux",
        arch="x86_64",
        agent_version="1.0.0",
        group_name=group,
        last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    db.add(host)
    await db.commit()
    await db.refresh(host)
    return host


# --------------------------------------------------------------------------- #
# Catch-all redirects
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dash_root_redirects_to_spa(client: AsyncClient) -> None:
    """``GET /dash/`` -> 302 ``/dash-next/``."""
    # No auth needed — the redirect is unconditional.
    resp = await client.get("/dash/", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/dash-next/"


@pytest.mark.asyncio
async def test_dash_root_no_slash_redirects_to_spa(client: AsyncClient) -> None:
    """``GET /dash`` (no trailing slash) -> 302 ``/dash-next/``.

    FastAPI's default ``redirect_slashes=True`` will first 307 ``/dash`` to
    ``/dash/``; we follow that single hop and then expect our own 302 to
    the SPA. The httpx client lets us inspect every hop via ``history``.
    """
    resp = await client.get("/dash", follow_redirects=True)

    # The terminal response must be the SPA shell (or a 404 if the static
    # mount is empty in tests). Either way, somewhere along the chain we
    # land on /dash-next/.
    final = str(resp.url)
    assert "/dash-next" in final


@pytest.mark.asyncio
async def test_dash_hosts_redirects_to_spa_hosts(client: AsyncClient) -> None:
    """``GET /dash/hosts`` -> 302 ``/dash-next/hosts``."""
    resp = await client.get("/dash/hosts", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/dash-next/hosts"


@pytest.mark.asyncio
async def test_dash_hosts_refresh_redirects_to_spa_hosts(client: AsyncClient) -> None:
    """The old HTMX ``/dash/hosts/refresh`` polling URL maps to SPA hosts."""
    resp = await client.get("/dash/hosts/refresh", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/dash-next/hosts"


@pytest.mark.asyncio
async def test_dash_host_detail_redirects_to_spa_host_detail(
    client: AsyncClient,
) -> None:
    """``/dash/host/{id}`` -> ``/dash-next/hosts/{id}`` (host -> hosts)."""
    host_id = uuid.uuid4()
    resp = await client.get(f"/dash/host/{host_id}", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == f"/dash-next/hosts/{host_id}"


@pytest.mark.asyncio
async def test_redirect_preserves_query_string(client: AsyncClient) -> None:
    """Query string survives the redirect."""
    resp = await client.get(
        "/dash/?group_filter=family", follow_redirects=False
    )

    assert resp.status_code == 302
    assert resp.headers["location"] == "/dash-next/?group_filter=family"


@pytest.mark.asyncio
async def test_redirect_preserves_query_string_on_subpath(
    client: AsyncClient,
) -> None:
    """Query string survives for sub-paths too."""
    resp = await client.get(
        "/dash/hosts?group_filter=prod&q=foo", follow_redirects=False
    )

    assert resp.status_code == 302
    # Order of query params is preserved by httpx/Starlette.
    assert resp.headers["location"] == "/dash-next/hosts?group_filter=prod&q=foo"


@pytest.mark.asyncio
async def test_unknown_subpath_falls_back_to_spa_root(client: AsyncClient) -> None:
    """An unknown sub-path lands on ``/dash-next/`` (SPA client router decides)."""
    resp = await client.get("/dash/totally-not-a-real-page", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/dash-next/"


@pytest.mark.asyncio
async def test_known_spa_sections_redirect_directly(client: AsyncClient) -> None:
    """``/dash/commands``, ``/dash/approvals``, ``/dash/audit`` map 1:1."""
    for section in ("commands", "approvals", "audit", "enroll", "settings"):
        resp = await client.get(f"/dash/{section}", follow_redirects=False)
        assert resp.status_code == 302, section
        assert resp.headers["location"] == f"/dash-next/{section}", section


# --------------------------------------------------------------------------- #
# Preserved endpoint: /dash/host/{id}/sparkline-data
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sparkline_data_route_is_registered(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """The preserved sparkline-data endpoint is NOT swallowed by the catch-all.

    With a known-bad host UUID the endpoint reaches its own host-lookup
    branch and returns 404 ("Host not found or access denied") — *not*
    a 302 from the catch-all redirect. That single signal proves:
    auth dependency ran, the route matched ``/dash/host/{id}/sparkline-data``,
    and the redirect router didn't shadow it.

    We deliberately avoid the SQL ``time_bucket`` path here: TimescaleDB
    is unavailable on the SQLite test fixture. The success path is
    covered in CI's Postgres job by existing F5 integration tests.
    """
    admin = await _make_admin(test_db)
    _override_user(admin)
    missing_host_id = uuid.uuid4()

    try:
        resp = await client.get(
            f"/dash/host/{missing_host_id}/sparkline-data",
            follow_redirects=False,
        )
    finally:
        _clear_user_override()

    # NOT a 302 from the catch-all redirect.
    assert resp.status_code != 302
    # The route is registered and dispatched to the sparkline handler,
    # which then returns its own 404 because no host with that id exists.
    assert resp.status_code == 404
    body = resp.json()
    assert "Host not found" in body.get("detail", "")


@pytest.mark.asyncio
async def test_sparkline_data_requires_auth(client: AsyncClient) -> None:
    """Without an authenticated user, sparkline-data returns 401 (not 302)."""
    _clear_user_override()
    resp = await client.get(
        f"/dash/host/{uuid.uuid4()}/sparkline-data",
        follow_redirects=False,
    )

    assert resp.status_code == 401
