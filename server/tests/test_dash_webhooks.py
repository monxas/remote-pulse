"""Tests for outbound webhooks subsystem.

Covers:
- CRUD + permission gating (`/v1/dash/webhooks`)
- Secret returned exactly once
- HMAC signature + header contract
- Filter matching (event prefix, exact, group filter)
- Retry behaviour on 5xx
- Auto-disable after 10 consecutive failures
- Test-fire endpoint
- Real bus event triggering delivery
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rp_server.deps import current_user
from rp_server.events import event_bus
from rp_server.main import app
from rp_server.models import User, Webhook
from rp_server.webhooks import (
    AUTO_DISABLE_AFTER,
    MAX_ATTEMPTS,
    TEST_EVENT_TYPE,
    RETRY_BACKOFF_SECONDS,
    WebhookDispatcher,
    _event_matches_filter,
    _group_matches_filter,
    compute_signature,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _override_user(user: User) -> None:
    async def _fake() -> User:
        return user

    app.dependency_overrides[current_user] = _fake


def _clear() -> None:
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


async def _make_webhook(
    db: AsyncSession,
    *,
    enabled: bool = True,
    event_filter: list[str] | None = None,
    group_filter: list[str] | None = None,
    failure_count: int = 0,
) -> Webhook:
    w = Webhook(
        name=f"hook-{uuid.uuid4().hex[:6]}",
        url="https://example.invalid/wh",
        secret="s3cr3t-" + uuid.uuid4().hex,
        event_filter=event_filter or ["*"],
        group_filter=group_filter,
        enabled=enabled,
        created_by="admin@test.local",
        failure_count=failure_count,
        recent_deliveries=[],
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


# --------------------------------------------------------------------------- #
# Permission gating
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_viewer_blocked(client: AsyncClient, test_db: AsyncSession) -> None:
    viewer = await _make_user(test_db, role="viewer")
    _override_user(viewer)
    try:
        for path in ("/v1/dash/webhooks",):
            assert (await client.get(path)).status_code == 403
        r = await client.post(
            "/v1/dash/webhooks",
            json={"name": "x", "url": "https://x", "event_filter": ["*"]},
        )
        assert r.status_code == 403
    finally:
        _clear()


@pytest.mark.asyncio
async def test_operator_blocked(client: AsyncClient, test_db: AsyncSession) -> None:
    op = await _make_user(test_db, role="operator")
    _override_user(op)
    try:
        assert (await client.get("/v1/dash/webhooks")).status_code == 403
    finally:
        _clear()


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_returns_secret_once(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/webhooks",
            json={
                "name": "n8n bridge",
                "url": "https://n8n.example/webhook/rp",
                "event_filter": ["command.", "approval."],
                "group_filter": ["prod"],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "secret" in body
        assert len(body["secret"]) == 64  # 32 bytes hex
        assert body["name"] == "n8n bridge"
        assert body["event_filter"] == ["command.", "approval."]
        assert body["group_filter"] == ["prod"]
        wid = body["id"]

        # Subsequent GETs do NOT include the secret.
        r2 = await client.get(f"/v1/dash/webhooks/{wid}")
        assert r2.status_code == 200
        assert "secret" not in r2.json()

        # List endpoint also omits secret.
        r3 = await client.get("/v1/dash/webhooks")
        assert r3.status_code == 200
        for entry in r3.json()["webhooks"]:
            assert "secret" not in entry
    finally:
        _clear()


@pytest.mark.asyncio
async def test_create_validates_url_and_filters(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        # plain http to non-loopback host → 422
        r = await client.post(
            "/v1/dash/webhooks",
            json={"name": "x", "url": "http://evil.example/", "event_filter": ["*"]},
        )
        assert r.status_code == 422, r.text

        # empty event_filter → 422
        r = await client.post(
            "/v1/dash/webhooks",
            json={"name": "x", "url": "https://ok.example/", "event_filter": []},
        )
        assert r.status_code == 422

        # bad event_filter entry → 422
        r = await client.post(
            "/v1/dash/webhooks",
            json={
                "name": "x",
                "url": "https://ok.example/",
                "event_filter": ["NotValid!"],
            },
        )
        assert r.status_code == 422

        # http to RFC1918 is allowed
        r = await client.post(
            "/v1/dash/webhooks",
            json={
                "name": "n8n",
                "url": "http://192.168.0.50:5678/webhook",
                "event_filter": ["*"],
            },
        )
        assert r.status_code == 201, r.text
    finally:
        _clear()


@pytest.mark.asyncio
async def test_patch_updates_fields_but_not_secret(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    w = await _make_webhook(test_db)
    original_secret = w.secret
    _override_user(admin)
    try:
        r = await client.patch(
            f"/v1/dash/webhooks/{w.id}",
            json={"name": "renamed", "enabled": False, "event_filter": ["host."]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "renamed"
        assert body["enabled"] is False
        assert body["event_filter"] == ["host."]
        assert "secret" not in body

        # Trying to send a secret in the body is silently ignored.
        r2 = await client.patch(
            f"/v1/dash/webhooks/{w.id}",
            json={"secret": "attempted-rotation"},
        )
        assert r2.status_code == 200
        # Confirm DB unchanged.
        await test_db.refresh(w)
        assert w.secret == original_secret
    finally:
        _clear()


@pytest.mark.asyncio
async def test_delete_returns_204(client: AsyncClient, test_db: AsyncSession) -> None:
    admin = await _make_user(test_db, role="admin")
    w = await _make_webhook(test_db)
    _override_user(admin)
    try:
        r = await client.delete(f"/v1/dash/webhooks/{w.id}")
        assert r.status_code == 204
        r2 = await client.get(f"/v1/dash/webhooks/{w.id}")
        assert r2.status_code == 404
    finally:
        _clear()


# --------------------------------------------------------------------------- #
# Filter logic (pure unit)
# --------------------------------------------------------------------------- #


def test_event_filter_exact_and_prefix() -> None:
    assert _event_matches_filter("command.issued", ["*"]) is True
    assert _event_matches_filter("command.issued", ["command."]) is True
    assert _event_matches_filter("command.issued", ["command.issued"]) is True
    assert _event_matches_filter("host.heartbeat", ["command."]) is False
    assert _event_matches_filter("approval.created", ["command.", "approval."]) is True


def test_group_filter() -> None:
    # No filter → match
    assert _group_matches_filter({"group_name": "prod"}, None) is True
    assert _group_matches_filter({"group_name": "prod"}, []) is True
    # Match by group_name
    assert _group_matches_filter({"group_name": "prod"}, ["prod", "stage"]) is True
    assert _group_matches_filter({"group_name": "prod"}, ["stage"]) is False
    # Match by alias 'group'
    assert _group_matches_filter({"group": "family"}, ["family"]) is True
    # No group in payload → allow through (don't accidentally drop)
    assert _group_matches_filter({"foo": "bar"}, ["prod"]) is True


def test_compute_signature_format() -> None:
    body = b'{"event":"x"}'
    secret = "abc"
    sig = compute_signature(body, secret)
    assert sig.startswith("sha256=")
    expected = hmac.new(b"abc", body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


# --------------------------------------------------------------------------- #
# Dispatcher delivery (mocked transport)
# --------------------------------------------------------------------------- #


class _RecordingTransport(httpx.AsyncBaseTransport):
    """httpx transport that records every request + returns canned responses."""

    def __init__(self, responses: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []
        # Default: always 200
        self._responses = responses or [200]
        self._idx = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # read() so we can introspect the body after the fact
        self.bodies.append(request.content)
        status = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return httpx.Response(status, request=request)


def _session_factory_from(db: AsyncSession) -> async_sessionmaker:
    """Wrap the test session as a 'factory' that yields the same session.

    The dispatcher opens its own short-lived sessions; we route every
    `async with factory()` to the per-test in-memory DB. Calling close()
    on the returned async cm is a no-op so subsequent calls still work.
    """

    class _Factory:
        def __call__(self):  # type: ignore[override]
            return _FakeCtx(db)

    class _FakeCtx:
        def __init__(self, sess: AsyncSession) -> None:
            self._sess = sess

        async def __aenter__(self) -> AsyncSession:
            return self._sess

        async def __aexit__(self, *_exc: object) -> None:
            return None

    return _Factory()  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_dispatch_success_signs_body_and_resets_counter(
    test_db: AsyncSession,
) -> None:
    w = await _make_webhook(
        test_db, event_filter=["command."], failure_count=3
    )
    transport = _RecordingTransport(responses=[200])
    client = httpx.AsyncClient(transport=transport)
    dispatcher = WebhookDispatcher(
        _session_factory_from(test_db), http_client=client
    )
    try:
        await dispatcher._dispatch(
            {"id": w.id, "url": w.url, "secret": w.secret},
            "command.issued",
            {"host_id": "abc", "group_name": "prod"},
        )
    finally:
        await client.aclose()

    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert req.headers["X-RP-Event-Type"] == "command.issued"
    assert req.headers["X-RP-Delivery-Id"]
    assert req.headers["X-RP-Timestamp"]
    sig_header = req.headers["X-RP-Signature-256"]
    expected = compute_signature(transport.bodies[0], w.secret)
    assert sig_header == expected

    # Body parses, carries envelope shape
    envelope = json.loads(transport.bodies[0])
    assert envelope["event"] == "command.issued"
    assert envelope["data"]["host_id"] == "abc"

    # Counter reset + history appended
    await test_db.refresh(w)
    assert w.failure_count == 0
    assert w.last_status_code == 200
    assert len(w.recent_deliveries) == 1
    assert w.recent_deliveries[0]["success"] is True


@pytest.mark.asyncio
async def test_dispatch_retries_then_records_failure(
    test_db: AsyncSession, monkeypatch
) -> None:
    # Shrink backoff to keep the test fast.
    monkeypatch.setattr(
        "rp_server.webhooks.RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0, 0.0)
    )
    w = await _make_webhook(test_db)
    transport = _RecordingTransport(responses=[500, 500, 500, 500])
    client = httpx.AsyncClient(transport=transport)
    dispatcher = WebhookDispatcher(
        _session_factory_from(test_db), http_client=client
    )
    try:
        await dispatcher._dispatch(
            {"id": w.id, "url": w.url, "secret": w.secret},
            "command.issued",
            {"host_id": "abc"},
        )
    finally:
        await client.aclose()

    assert len(transport.requests) == MAX_ATTEMPTS
    await test_db.refresh(w)
    assert w.failure_count == 1
    assert w.last_status_code == 500
    assert w.last_error == "HTTP 500"


@pytest.mark.asyncio
async def test_auto_disable_after_threshold(
    test_db: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(
        "rp_server.webhooks.RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0, 0.0)
    )
    # Start one short of the auto-disable threshold.
    w = await _make_webhook(test_db, failure_count=AUTO_DISABLE_AFTER - 1)
    transport = _RecordingTransport(responses=[500, 500, 500, 500])
    client = httpx.AsyncClient(transport=transport)
    dispatcher = WebhookDispatcher(
        _session_factory_from(test_db), http_client=client
    )
    try:
        await dispatcher._dispatch(
            {"id": w.id, "url": w.url, "secret": w.secret},
            "command.issued",
            {"host_id": "abc"},
        )
    finally:
        await client.aclose()

    await test_db.refresh(w)
    assert w.failure_count == AUTO_DISABLE_AFTER
    assert w.enabled is False


@pytest.mark.asyncio
async def test_group_filter_skips_non_matching_event(
    test_db: AsyncSession,
) -> None:
    # `_find_matches` looks up enabled rows and applies filters in Python.
    w_prod = await _make_webhook(
        test_db, event_filter=["host."], group_filter=["prod"]
    )
    w_any = await _make_webhook(test_db, event_filter=["host."])  # no group filter

    dispatcher = WebhookDispatcher(_session_factory_from(test_db))
    matches = await dispatcher._find_matches(
        "host.status_change", {"group_name": "family"}
    )
    ids = {m["id"] for m in matches}
    # w_prod skipped (group mismatch), w_any included.
    assert w_any.id in ids
    assert w_prod.id not in ids


# --------------------------------------------------------------------------- #
# Test-fire endpoint + end-to-end via the bus
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_test_endpoint_publishes_and_dispatcher_routes_it(
    client: AsyncClient, test_db: AsyncSession, monkeypatch
) -> None:
    monkeypatch.setattr(
        "rp_server.webhooks.RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0, 0.0)
    )
    admin = await _make_user(test_db, role="admin")
    w = await _make_webhook(test_db, event_filter=["webhook."])

    transport = _RecordingTransport(responses=[200])
    http = httpx.AsyncClient(transport=transport)
    dispatcher = WebhookDispatcher(
        _session_factory_from(test_db), http_client=http
    )
    dispatcher.start()
    # Wait for the subscriber to actually attach to the bus.
    for _ in range(10):
        await asyncio.sleep(0.01)
        if event_bus.subscriber_count > 0:
            break

    _override_user(admin)
    try:
        r = await client.post(f"/v1/dash/webhooks/{w.id}/test")
        assert r.status_code == 202, r.text
        # Give the subscriber + dispatch tasks a tick or two.
        for _ in range(40):
            await asyncio.sleep(0.05)
            if transport.requests:
                break
        assert len(transport.requests) == 1
        assert (
            transport.requests[0].headers["X-RP-Event-Type"] == TEST_EVENT_TYPE
        )
    finally:
        _clear()
        await dispatcher.stop()
        await http.aclose()


@pytest.mark.asyncio
async def test_real_bus_event_triggers_delivery(
    test_db: AsyncSession, monkeypatch
) -> None:
    """Publishing on the bus should reach a matching webhook."""
    monkeypatch.setattr(
        "rp_server.webhooks.RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0, 0.0)
    )
    w = await _make_webhook(test_db, event_filter=["command."])

    transport = _RecordingTransport(responses=[200])
    http = httpx.AsyncClient(transport=transport)
    dispatcher = WebhookDispatcher(
        _session_factory_from(test_db), http_client=http
    )
    dispatcher.start()
    # Give the subscriber task a tick to attach to the bus before we
    # publish — otherwise the publish can race past an empty subscriber
    # set and the dispatcher's queue never sees the event.
    for _ in range(10):
        await asyncio.sleep(0.01)
        if event_bus.subscriber_count > 0:
            break
    try:
        await event_bus.publish(
            "command.issued", {"host_id": "abc", "group_name": "prod"}
        )
        for _ in range(40):
            await asyncio.sleep(0.05)
            if transport.requests:
                break
        assert len(transport.requests) >= 1
        assert (
            transport.requests[0].headers["X-RP-Event-Type"] == "command.issued"
        )
    finally:
        await dispatcher.stop()
        await http.aclose()


@pytest.mark.asyncio
async def test_deliveries_endpoint_returns_history(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    w = await _make_webhook(test_db)
    w.recent_deliveries = [
        {
            "delivery_id": str(uuid.uuid4()),
            "event": "command.issued",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status_code": 200,
            "error": None,
            "attempt": 1,
            "success": True,
        },
        {
            "delivery_id": str(uuid.uuid4()),
            "event": "host.heartbeat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status_code": 502,
            "error": "HTTP 502",
            "attempt": 4,
            "success": False,
        },
    ]
    await test_db.commit()

    _override_user(admin)
    try:
        r = await client.get(f"/v1/dash/webhooks/{w.id}/deliveries")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["webhook_id"] == str(w.id)
        assert len(body["deliveries"]) == 2
        # Newest first (we put the failed one second above).
        assert body["deliveries"][0]["success"] is False
    finally:
        _clear()


@pytest.mark.asyncio
async def test_audit_rows_emitted_on_crud(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Create/update/delete/test should each emit an audit_events row."""
    from sqlalchemy import select
    from rp_server.models import AuditEvent

    admin = await _make_user(test_db, role="admin")
    _override_user(admin)
    try:
        r = await client.post(
            "/v1/dash/webhooks",
            json={
                "name": "audited",
                "url": "https://ok.example/wh",
                "event_filter": ["*"],
            },
        )
        wid = r.json()["id"]
        await client.patch(
            f"/v1/dash/webhooks/{wid}", json={"name": "renamed"}
        )
        await client.post(f"/v1/dash/webhooks/{wid}/test")
        await client.delete(f"/v1/dash/webhooks/{wid}")

        rows = (
            (
                await test_db.execute(
                    select(AuditEvent).where(AuditEvent.resource_type == "webhook")
                )
            )
            .scalars()
            .all()
        )
        actions = {r.action for r in rows}
        assert {"webhook.created", "webhook.updated", "webhook.tested", "webhook.deleted"} <= actions
    finally:
        _clear()
