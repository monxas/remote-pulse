"""Tests for the webhook deliveries surface added in v1.0.12+.

Covers:
- ``POST /v1/dash/webhooks/{id}/deliveries/{delivery_id}/retry``:
  admin success path, non-admin 403, unknown delivery 404, audit row,
  ``retry_of`` marker propagated to the recorded record.
- ``POST /v1/dash/webhooks/{id}/reset-failures``: clears ``failure_count``,
  re-enables the hook, emits audit.

The dispatcher itself is stubbed via ``set_dispatcher`` with a fake so we
don't need an httpx transport for these tests — the retry endpoint just
needs to confirm that *something* was scheduled with the right shape.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.deps import current_user
from rp_server.main import app
from rp_server.models import AuditEvent, User, Webhook
from rp_server.webhooks import get_dispatcher, set_dispatcher


# --------------------------------------------------------------------------- #
# Test plumbing — kept minimal and self-contained so this file stands alone
# from test_dash_webhooks.py.
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
    failure_count: int = 0,
    deliveries: list[dict] | None = None,
) -> Webhook:
    w = Webhook(
        name=f"hook-{uuid.uuid4().hex[:6]}",
        url="https://example.invalid/wh",
        secret="s3cr3t-" + uuid.uuid4().hex,
        event_filter=["*"],
        group_filter=None,
        enabled=enabled,
        created_by="admin@test.local",
        failure_count=failure_count,
        recent_deliveries=deliveries or [],
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


def _make_delivery_entry(
    *,
    delivery_id: str | None = None,
    event: str = "command.issued",
    status_code: int | None = 500,
    success: bool = False,
) -> dict:
    return {
        "delivery_id": delivery_id or str(uuid.uuid4()),
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status_code": status_code,
        "error": None if success else f"HTTP {status_code}",
        "attempt": 1 if success else 4,
        "success": success,
    }


class _FakeDispatcher:
    """Captures retry calls without touching the network.

    Mirrors the public ``dispatch_retry`` signature used by the router so
    we can assert exactly what the endpoint scheduled. The retry endpoint
    schedules the call via ``asyncio.create_task`` so we await one event
    loop turn in the tests to drain it.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def dispatch_retry(
        self,
        hook: dict,
        event_type: str,
        payload: dict,
        *,
        retry_of: str,
    ) -> None:
        self.calls.append(
            {
                "hook_id": str(hook["id"]),
                "url": hook["url"],
                "event_type": event_type,
                "payload": payload,
                "retry_of": retry_of,
            }
        )


# --------------------------------------------------------------------------- #
# Retry endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_retry_admin_schedules_redelivery(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Happy path: admin re-fires a failed delivery, audit row emitted."""
    original = _make_delivery_entry(status_code=502)
    w = await _make_webhook(test_db, deliveries=[original])
    admin = await _make_user(test_db, role="admin")

    fake = _FakeDispatcher()
    previous = get_dispatcher()
    set_dispatcher(fake)  # type: ignore[arg-type]
    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/webhooks/{w.id}/deliveries/{original['delivery_id']}/retry"
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "queued"
        assert body["retry_of"] == original["delivery_id"]

        # Drain the scheduled task so the fake dispatcher records it.
        for _ in range(20):
            await asyncio.sleep(0)
            if fake.calls:
                break
        assert len(fake.calls) == 1, "retry was not scheduled"
        call = fake.calls[0]
        assert call["retry_of"] == original["delivery_id"]
        assert call["event_type"] == original["event"]
        assert call["payload"]["retry_of"] == original["delivery_id"]
        assert call["url"] == w.url

        # Audit row emitted with the expected action key.
        rows = (
            (
                await test_db.execute(
                    select(AuditEvent).where(
                        AuditEvent.resource_type == "webhook",
                        AuditEvent.resource_id == str(w.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        actions = {r.action for r in rows}
        assert "webhook.delivery.retried" in actions
    finally:
        _clear()
        set_dispatcher(previous)


@pytest.mark.asyncio
async def test_retry_non_admin_forbidden(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Operators and viewers must get a 403 from the retry endpoint."""
    original = _make_delivery_entry()
    w = await _make_webhook(test_db, deliveries=[original])
    op = await _make_user(test_db, role="operator")

    fake = _FakeDispatcher()
    previous = get_dispatcher()
    set_dispatcher(fake)  # type: ignore[arg-type]
    _override_user(op)
    try:
        r = await client.post(
            f"/v1/dash/webhooks/{w.id}/deliveries/{original['delivery_id']}/retry"
        )
        assert r.status_code == 403
        # And no dispatch was scheduled.
        await asyncio.sleep(0)
        assert fake.calls == []
    finally:
        _clear()
        set_dispatcher(previous)


@pytest.mark.asyncio
async def test_retry_unknown_delivery_404(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Delivery rolled out of the sliding window → 404 with friendly detail."""
    w = await _make_webhook(test_db, deliveries=[_make_delivery_entry()])
    admin = await _make_user(test_db, role="admin")

    fake = _FakeDispatcher()
    previous = get_dispatcher()
    set_dispatcher(fake)  # type: ignore[arg-type]
    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/webhooks/{w.id}/deliveries/{uuid.uuid4()}/retry"
        )
        assert r.status_code == 404
        assert "retention window" in r.json()["detail"].lower()
    finally:
        _clear()
        set_dispatcher(previous)


@pytest.mark.asyncio
async def test_retry_unknown_webhook_404(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    admin = await _make_user(test_db, role="admin")
    fake = _FakeDispatcher()
    previous = get_dispatcher()
    set_dispatcher(fake)  # type: ignore[arg-type]
    _override_user(admin)
    try:
        r = await client.post(
            f"/v1/dash/webhooks/{uuid.uuid4()}/deliveries/{uuid.uuid4()}/retry"
        )
        assert r.status_code == 404
    finally:
        _clear()
        set_dispatcher(previous)


# --------------------------------------------------------------------------- #
# Reset-failures endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reset_failures_clears_counter_and_reenables(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    """Auto-disabled hook → reset → counter 0 + enabled true + audit row."""
    w = await _make_webhook(test_db, enabled=False, failure_count=10)
    admin = await _make_user(test_db, role="admin")

    _override_user(admin)
    try:
        r = await client.post(f"/v1/dash/webhooks/{w.id}/reset-failures")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["failure_count"] == 0
        assert body["enabled"] is True

        await test_db.refresh(w)
        assert w.failure_count == 0
        assert w.enabled is True
        assert w.last_error is None

        rows = (
            (
                await test_db.execute(
                    select(AuditEvent).where(
                        AuditEvent.resource_type == "webhook",
                        AuditEvent.action == "webhook.failures_reset",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["before"]["failure_count"] == 10
        assert payload["before"]["enabled"] is False
    finally:
        _clear()


@pytest.mark.asyncio
async def test_reset_failures_non_admin_forbidden(
    client: AsyncClient, test_db: AsyncSession
) -> None:
    w = await _make_webhook(test_db, enabled=False, failure_count=10)
    op = await _make_user(test_db, role="operator")
    _override_user(op)
    try:
        r = await client.post(f"/v1/dash/webhooks/{w.id}/reset-failures")
        assert r.status_code == 403
    finally:
        _clear()


# --------------------------------------------------------------------------- #
# retry_of bookkeeping on the live dispatcher path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_retry_records_retry_of_marker(
    test_db: AsyncSession, monkeypatch
) -> None:
    """The real dispatcher path stamps ``retry_of`` on the recorded entry."""
    import httpx

    from rp_server.webhooks import WebhookDispatcher

    monkeypatch.setattr(
        "rp_server.webhooks.RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0, 0.0)
    )

    w = await _make_webhook(test_db)

    class _T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):  # type: ignore[override]
            return httpx.Response(200, request=request)

    http = httpx.AsyncClient(transport=_T())

    class _Factory:
        def __call__(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return test_db

                async def __aexit__(self_inner, *_exc):
                    return None

            return _Ctx()

    dispatcher = WebhookDispatcher(_Factory(), http_client=http)  # type: ignore[arg-type]
    try:
        await dispatcher.dispatch_retry(
            {"id": w.id, "url": w.url, "secret": w.secret},
            "command.issued",
            {"retry_of": "orig-123"},
            retry_of="orig-123",
        )
    finally:
        await http.aclose()

    await test_db.refresh(w)
    assert len(w.recent_deliveries) == 1
    assert w.recent_deliveries[0]["retry_of"] == "orig-123"
    assert w.recent_deliveries[0]["success"] is True
