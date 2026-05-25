"""Tests for the SvelteKit dashboard JSON API (ADR-0009 Phase 1).

These tests exercise ``/v1/dash/*``:
- ``/me``, ``/overview``, ``/hosts``, ``/hosts/{id}/timeseries``, ``/stream``
- Auth gating, group ACL, status classification, SQL-injection defense, SSE.

Auth is faked by overriding the ``current_user`` dependency at the app level
— a pattern used elsewhere in the codebase (see ``test_users_auth.py``).
For DB-touching tests we rely on the project's conftest ``test_db``
(SQLite) for simple cases and the real-Postgres test infra (CI) for time-
bucketed queries. Time-bucket queries are patched in tests that run against
SQLite by overriding the buffer-fetch helpers.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.events import event_bus
from rp_server.main import app
from rp_server.models import Host, User
from rp_server.routers import dash_api


# --------------------------------------------------------------------------- #
# Auth + DB helpers
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    """Inject a faked authenticated user into the FastAPI app."""

    async def _fake_current_user() -> User:
        return user

    app.dependency_overrides[current_user] = _fake_current_user


def _clear_user_override() -> None:
    app.dependency_overrides.pop(current_user, None)


async def _make_admin(db: AsyncSession) -> User:
    user = User(
        pocketid_sub="admin-test",
        email="admin@test.local",
        name="Admin",
        role="admin",
        accessible_groups=[],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_viewer(db: AsyncSession, groups: list[str]) -> User:
    user = User(
        pocketid_sub=f"viewer-{uuid.uuid4().hex[:8]}",
        email=f"viewer-{uuid.uuid4().hex[:8]}@test.local",
        name="Viewer",
        role="viewer",
        accessible_groups=groups,
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
    )
    db.add(host)
    await db.commit()
    await db.refresh(host)
    return host


# --------------------------------------------------------------------------- #
# /v1/dash/me
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_me_admin_returns_all_groups(client: AsyncClient, test_db: AsyncSession) -> None:
    """Admin's ``accessible_groups`` covers every distinct group in the DB."""
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="h1", group="prod")
    await _make_host(test_db, hostname="h2", group="family")
    await _make_host(test_db, hostname="h3", group="extern")
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/me")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "admin@test.local"
    assert body["role"] == "admin"
    assert sorted(body["accessible_groups"]) == ["extern", "family", "prod"]


@pytest.mark.asyncio
async def test_me_viewer_returns_own_groups(client: AsyncClient, test_db: AsyncSession) -> None:
    """Viewer's ``accessible_groups`` mirrors the user row (not the DB-wide list)."""
    viewer = await _make_viewer(test_db, groups=["family"])
    await _make_host(test_db, hostname="h1", group="prod")
    await _make_host(test_db, hostname="h2", group="family")
    _override_user(viewer)

    try:
        resp = await client.get("/v1/dash/me")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "viewer"
    assert body["accessible_groups"] == ["family"]


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient) -> None:
    """Missing auth → 401."""
    _clear_user_override()
    resp = await client.get("/v1/dash/me")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# /v1/dash/overview
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_overview_status_counts(client: AsyncClient, test_db: AsyncSession) -> None:
    """Online/stale/offline counts respect the 60s/180s thresholds."""
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="online-1", last_seen_s_ago=5)
    await _make_host(test_db, hostname="online-2", last_seen_s_ago=30)
    await _make_host(test_db, hostname="stale-1", last_seen_s_ago=120)
    await _make_host(test_db, hostname="offline-1", last_seen_s_ago=600)
    await _make_host(test_db, hostname="never-seen", last_seen_s_ago=None)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/overview")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert body["online"] == 2
    assert body["stale"] == 1
    assert body["offline"] == 2
    assert body["online_pct"] == 40.0
    assert body["pending_approvals"] == 0


@pytest.mark.asyncio
async def test_overview_respects_group_acl(client: AsyncClient, test_db: AsyncSession) -> None:
    """A viewer with one group sees only that group's hosts in the counts."""
    viewer = await _make_viewer(test_db, groups=["family"])
    await _make_host(test_db, hostname="family-1", group="family", last_seen_s_ago=10)
    await _make_host(test_db, hostname="prod-1", group="prod", last_seen_s_ago=10)
    await _make_host(test_db, hostname="prod-2", group="prod", last_seen_s_ago=10)
    _override_user(viewer)

    try:
        resp = await client.get("/v1/dash/overview")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["online"] == 1


@pytest.mark.asyncio
async def test_overview_empty_fleet(client: AsyncClient, test_db: AsyncSession) -> None:
    """Empty fleet → all-zero counts + online_pct=0."""
    admin = await _make_admin(test_db)
    _override_user(admin)
    try:
        resp = await client.get("/v1/dash/overview")
    finally:
        _clear_user_override()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["online_pct"] == 0.0
    assert body["online_pct_24h_ago"] is None


# --------------------------------------------------------------------------- #
# /v1/dash/hosts
# --------------------------------------------------------------------------- #


def _patch_sparkline_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the time_bucket helpers — SQLite has no TimescaleDB.

    Returns empty buffers; tests assert only on the shape/ACL/filter behaviour.
    """

    async def _empty_spark(
        db: Any, host_ids: list[uuid.UUID], window_s: int, bucket_s: int, now: datetime
    ) -> dict[uuid.UUID, dict[str, list[Any]]]:
        return {h: {"ts": [], "cpu_pct": [], "mem_pct": []} for h in host_ids}

    async def _empty_current(
        db: Any, host_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dash_api.CurrentMetrics]:
        return {h: dash_api.CurrentMetrics() for h in host_ids}

    monkeypatch.setattr(dash_api, "_fetch_sparkline_buffer", _empty_spark)
    monkeypatch.setattr(dash_api, "_fetch_current_metrics", _empty_current)


@pytest.mark.asyncio
async def test_hosts_basic_shape(
    client: AsyncClient,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/v1/dash/hosts`` returns enriched entries with sparkline buffer."""
    _patch_sparkline_helpers(monkeypatch)
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="aaa", group="prod", last_seen_s_ago=10)
    await _make_host(test_db, hostname="bbb", group="family", last_seen_s_ago=600)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/hosts")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert "hosts" in body and "groups" in body
    assert len(body["hosts"]) == 2
    # default window=5m, 60 buckets → bucket_s=5
    assert body["hosts"][0]["sparkline"]["window_s"] == 300
    assert body["hosts"][0]["sparkline"]["bucket_s"] == 5
    # Sorted by hostname
    assert [h["hostname"] for h in body["hosts"]] == ["aaa", "bbb"]
    # Status classification
    statuses = {h["hostname"]: h["status"] for h in body["hosts"]}
    assert statuses["aaa"] == "online"
    assert statuses["bbb"] == "offline"


@pytest.mark.asyncio
async def test_hosts_group_filter(
    client: AsyncClient,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``?group=family`` narrows the result set."""
    _patch_sparkline_helpers(monkeypatch)
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="prod-1", group="prod", last_seen_s_ago=10)
    await _make_host(test_db, hostname="fam-1", group="family", last_seen_s_ago=10)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/hosts?group=family")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["hosts"]) == 1
    assert body["hosts"][0]["hostname"] == "fam-1"


@pytest.mark.asyncio
async def test_hosts_status_filter(
    client: AsyncClient,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``?status=offline`` keeps only offline hosts."""
    _patch_sparkline_helpers(monkeypatch)
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="alive", last_seen_s_ago=10)
    await _make_host(test_db, hostname="dead", last_seen_s_ago=999)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/hosts?status=offline")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert [h["hostname"] for h in body["hosts"]] == ["dead"]


@pytest.mark.asyncio
async def test_hosts_q_substring(
    client: AsyncClient,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``?q=foo`` matches hostnames case-insensitively."""
    _patch_sparkline_helpers(monkeypatch)
    admin = await _make_admin(test_db)
    await _make_host(test_db, hostname="FoO-server", last_seen_s_ago=10)
    await _make_host(test_db, hostname="bar-server", last_seen_s_ago=10)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/hosts?q=foo")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert [h["hostname"] for h in body["hosts"]] == ["FoO-server"]


@pytest.mark.asyncio
async def test_hosts_invalid_window_rejected(
    client: AsyncClient,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown ``window`` value → 400."""
    _patch_sparkline_helpers(monkeypatch)
    admin = await _make_admin(test_db)
    _override_user(admin)

    try:
        resp = await client.get("/v1/dash/hosts?window=99h")
    finally:
        _clear_user_override()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_hosts_viewer_acl(
    client: AsyncClient,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viewer only sees hosts in their accessible_groups."""
    _patch_sparkline_helpers(monkeypatch)
    viewer = await _make_viewer(test_db, groups=["family"])
    await _make_host(test_db, hostname="prod-1", group="prod", last_seen_s_ago=10)
    await _make_host(test_db, hostname="fam-1", group="family", last_seen_s_ago=10)
    _override_user(viewer)

    try:
        resp = await client.get("/v1/dash/hosts")
    finally:
        _clear_user_override()

    assert resp.status_code == 200
    body = resp.json()
    assert [h["hostname"] for h in body["hosts"]] == ["fam-1"]
    assert body["groups"] == ["family"]


# --------------------------------------------------------------------------- #
# /v1/dash/hosts/{host_id}/timeseries
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_timeseries_acl_404_for_other_groups(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    """Viewer cannot read a host outside their accessible_groups (collapsed to 404)."""
    viewer = await _make_viewer(test_db, groups=["family"])
    host = await _make_host(test_db, hostname="forbidden", group="prod", last_seen_s_ago=10)
    _override_user(viewer)

    try:
        resp = await client.get(f"/v1/dash/hosts/{host.id}/timeseries")
    finally:
        _clear_user_override()

    assert resp.status_code == 404
    assert "access denied" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_timeseries_invalid_window(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    """Unknown window string is rejected before touching the DB."""
    admin = await _make_admin(test_db)
    host = await _make_host(test_db, hostname="h", last_seen_s_ago=10)
    _override_user(admin)

    try:
        resp = await client.get(f"/v1/dash/hosts/{host.id}/timeseries?window=99h")
    finally:
        _clear_user_override()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_timeseries_sql_injection_defense(
    client: AsyncClient,
    test_db: AsyncSession,
) -> None:
    """Hostile ``series`` value (not in ALLOWED_METRICS) is rejected.

    Two attack shapes:
      1. Non-allowed metric ⇒ filtered out, request 400 if nothing valid.
      2. Allowed metric + injection ⇒ filtered out (only one survives).
    """
    admin = await _make_admin(test_db)
    host = await _make_host(test_db, hostname="h", last_seen_s_ago=10)
    _override_user(admin)

    try:
        # Pure attack ⇒ no valid metrics ⇒ 400
        resp = await client.get(
            f"/v1/dash/hosts/{host.id}/timeseries?series=cpu_pct;DROP TABLE hosts"
        )
        # Either Postgres-style or ; encoded — both should reject.
        assert resp.status_code in (400,)

        # Plain unknown metric ⇒ 400 (no valid metrics survive)
        resp = await client.get(f"/v1/dash/hosts/{host.id}/timeseries?series=evil_metric")
        assert resp.status_code == 400
    finally:
        _clear_user_override()


# --------------------------------------------------------------------------- #
# /v1/dash/stream — Server-Sent Events
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sse_receives_published_heartbeat() -> None:
    """Subscribe to ``event_bus`` and verify a published heartbeat arrives.

    We test the bus directly here (not the HTTP endpoint) because SSE over
    httpx requires streaming, and the per-process bus is what guarantees
    delivery — the HTTP endpoint is a thin wrapper around ``subscribe()``.
    """
    received: list[tuple[str, dict[str, Any]]] = []

    async def consume() -> None:
        async for ev_type, payload in event_bus.subscribe():
            received.append((ev_type, payload))
            if len(received) >= 1:
                break

    task = asyncio.create_task(consume())
    # Give the subscriber a chance to register before we publish.
    await asyncio.sleep(0.01)
    await event_bus.publish(
        "host.heartbeat",
        {"host_id": "deadbeef", "group_name": "prod", "cpu_pct": 12.0},
    )
    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 1
    assert received[0][0] == "host.heartbeat"
    assert received[0][1]["host_id"] == "deadbeef"


@pytest.mark.asyncio
async def test_sse_admin_visibility_filter() -> None:
    """``_event_visible_to_user`` lets admins see everything."""
    admin = User(
        pocketid_sub="admin-sse",
        email="admin@x",
        role="admin",
        accessible_groups=[],
    )
    assert dash_api._event_visible_to_user(admin, {"group_name": "prod"}) is True
    assert dash_api._event_visible_to_user(admin, {"group_name": None}) is True
    assert dash_api._event_visible_to_user(admin, {}) is True


@pytest.mark.asyncio
async def test_sse_viewer_visibility_filter() -> None:
    """Viewers only see events for their groups; untagged events are dropped."""
    viewer = User(
        pocketid_sub="viewer-sse",
        email="viewer@x",
        role="viewer",
        accessible_groups=["family"],
    )
    assert dash_api._event_visible_to_user(viewer, {"group_name": "family"}) is True
    assert dash_api._event_visible_to_user(viewer, {"group_name": "prod"}) is False
    # Untagged event → conservatively dropped (we don't leak across tenants).
    assert dash_api._event_visible_to_user(viewer, {}) is False


@pytest.mark.asyncio
async def test_event_bus_drops_on_full_queue() -> None:
    """A slow subscriber gets events dropped rather than blocking the publisher."""
    from rp_server.events import EventBus

    tiny_bus = EventBus(max_queue_size=2)

    received: list[tuple[str, dict[str, Any]]] = []
    stop = asyncio.Event()

    async def slow_consumer() -> None:
        async for ev in tiny_bus.subscribe():
            received.append(ev)
            await stop.wait()  # Block forever — fill the queue

    consumer_task = asyncio.create_task(slow_consumer())
    await asyncio.sleep(0.01)

    # Publish more than max_queue_size; extras should silently drop.
    for i in range(10):
        await tiny_bus.publish("e", {"i": i})
    await asyncio.sleep(0.05)

    # Subscriber count and dropped events shouldn't crash the bus.
    assert tiny_bus.subscriber_count == 1

    stop.set()
    consumer_task.cancel()
    try:
        await consumer_task
    except (asyncio.CancelledError, BaseException):
        pass


@pytest.mark.asyncio
async def test_sse_endpoint_streams_events(
    test_db: AsyncSession,
) -> None:
    """End-to-end: subscribe to ``/v1/dash/stream`` and assert we receive events.

    Uses a fresh ASGI transport so we can stream the response.
    """
    admin = User(
        pocketid_sub="admin-stream",
        email="admin-stream@test.local",
        role="admin",
        accessible_groups=[],
    )
    test_db.add(admin)
    await test_db.commit()
    await test_db.refresh(admin)
    _override_user(admin)

    from rp_server.database import get_db

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    received_events: list[str] = []
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:

            async def reader() -> None:
                async with ac.stream("GET", "/v1/dash/stream") as resp:
                    assert resp.status_code == 200
                    assert "text/event-stream" in resp.headers["content-type"]
                    async for line in resp.aiter_lines():
                        received_events.append(line)
                        if any("host.heartbeat" in e for e in received_events):
                            return

            reader_task = asyncio.create_task(reader())
            # Give the SSE handler time to subscribe.
            await asyncio.sleep(0.1)
            await event_bus.publish(
                "host.heartbeat",
                {"host_id": "abc", "group_name": "prod", "cpu_pct": 1.0},
            )
            try:
                await asyncio.wait_for(reader_task, timeout=3.0)
            except asyncio.TimeoutError:
                reader_task.cancel()
                pytest.fail(
                    f"SSE event not received in time. Buffer: {received_events!r}"
                )
    finally:
        _clear_user_override()
        app.dependency_overrides.pop(get_db, None)

    assert any("event: host.heartbeat" in line for line in received_events), (
        f"expected host.heartbeat event in: {received_events!r}"
    )
