"""Outbound webhook dispatcher.

Subscribes to the in-process :mod:`rp_server.events` bus and forwards
matching events to externally configured URLs as signed JSON POSTs.

Delivery contract
-----------------
A delivery is a POST with::

    Content-Type: application/json
    X-RP-Event-Type: <event_type>
    X-RP-Delivery-Id: <uuid>
    X-RP-Timestamp:  <iso8601 utc>
    X-RP-Signature-256: sha256=<HMAC-SHA256(body, secret)>

The body is::

    {
        "event": "<event_type>",
        "delivery_id": "<uuid>",
        "timestamp": "<iso8601 utc>",
        "data": { ...event payload as published on the bus... }
    }

Retries
-------
Up to 3 attempts (1s -> 5s -> 30s backoff) with a 10s per-request
timeout. After the final attempt fails we bump ``failure_count`` on the
row; ``failure_count >= AUTO_DISABLE_AFTER`` flips ``enabled = false`` so
a broken consumer can't gum up the dispatcher forever. A successful
delivery resets the counter.

Why fire-and-forget
-------------------
The bus emit hot path (heartbeat) must never block on a slow webhook
receiver. We schedule the entire match + dispatch as a background task;
if the loop is saturated, dispatches just queue up. The replay buffer in
``EventBus`` is the safety net for slow subscribers in general.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from rp_server.events import event_bus
from rp_server.models import Webhook

logger = logging.getLogger(__name__)

# ---- Tunables ------------------------------------------------------------- #

#: Per-request timeout (connect + read). Webhook receivers should respond
#: with a 2xx within this window or the attempt is treated as a failure.
HTTP_TIMEOUT_SECONDS: float = 10.0

#: Retry schedule. ``len(...) == max_attempts``. First entry is the wait
#: BEFORE the first attempt (always 0 in practice).
RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.0, 1.0, 5.0, 30.0)
#: First entry above is the initial "wait", remaining are backoffs between
#: retries — total attempts = ``len(RETRY_BACKOFF_SECONDS) - 1`` (wait,
#: try, wait, try ...). With (0, 1, 5, 30) we get 3 retries after the
#: first try, i.e. 4 attempts total. The spec calls for "3 retries"
#: which usually means 3 retries after the first, so 4 total — we go
#: with that reading.
MAX_ATTEMPTS: int = len(RETRY_BACKOFF_SECONDS)

#: Auto-disable threshold: a hook with this many consecutive failures
#: flips ``enabled = false`` and stops receiving deliveries.
AUTO_DISABLE_AFTER: int = 10

#: Cap on the JSONB sliding window per row. Older entries are dropped
#: as new ones arrive so the row stays bounded.
MAX_DELIVERY_HISTORY: int = 20

#: Synthetic event type used by the "Test" admin endpoint to probe a
#: webhook end-to-end without waiting for a real event. Match-by-prefix
#: filters (e.g. ``"webhook."``) catch this; exact matches (e.g.
#: ``"webhook.test"``) do too.
TEST_EVENT_TYPE: str = "webhook.test"


# ---- Signing -------------------------------------------------------------- #


def generate_secret() -> str:
    """Return a 32-byte hex-encoded random secret (64 chars)."""
    return secrets.token_hex(32)


def compute_signature(body: bytes, secret: str) -> str:
    """Return ``sha256=<hex>`` HMAC over ``body`` using ``secret``."""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


# ---- Filter matching ------------------------------------------------------ #


def _event_matches_filter(event_type: str, filt: list[str]) -> bool:
    """Return True if ``event_type`` matches any entry in ``filt``.

    Entries ending in ``.`` (e.g. ``"command."``) match anything with that
    prefix. ``"*"`` matches everything. Otherwise the match is exact.
    """
    for entry in filt:
        if entry == "*":
            return True
        if entry.endswith("."):
            if event_type.startswith(entry):
                return True
        elif entry == event_type:
            return True
    return False


def _group_matches_filter(payload: dict[str, Any], filt: list[str] | None) -> bool:
    """Return True if the event payload's group satisfies ``filt``.

    ``filt`` of ``None`` or empty list means "any group". The payload's
    group is looked up under the canonical keys we emit (``group_name``
    and ``group``); if neither is present we let the event through —
    forcing a group on events that don't carry one would silently drop
    legitimate matches.
    """
    if not filt:
        return True
    group = payload.get("group_name") or payload.get("group")
    if group is None:
        return True
    return group in filt


# ---- Body construction ---------------------------------------------------- #


def _build_delivery(
    *,
    event_type: str,
    payload: dict[str, Any],
    delivery_id: str | None = None,
    timestamp: _dt.datetime | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Return the ``(envelope, encoded_body)`` for a delivery."""
    delivery_id = delivery_id or str(uuid.uuid4())
    ts = (timestamp or _dt.datetime.now(_dt.timezone.utc)).isoformat()
    envelope = {
        "event": event_type,
        "delivery_id": delivery_id,
        "timestamp": ts,
        "data": payload,
    }
    body = json.dumps(envelope, default=str, separators=(",", ":")).encode("utf-8")
    return envelope, body


# ---- Persistence helpers -------------------------------------------------- #


def _append_delivery_history(
    existing: list[dict[str, Any]] | None,
    entry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return a new list = ``existing + [entry]`` truncated to the cap."""
    history = list(existing or [])
    history.append(entry)
    if len(history) > MAX_DELIVERY_HISTORY:
        history = history[-MAX_DELIVERY_HISTORY:]
    return history


async def _record_result(
    session_factory: async_sessionmaker,
    webhook_id: uuid.UUID,
    *,
    delivery_id: str,
    event_type: str,
    success: bool,
    status_code: int | None,
    error: str | None,
    attempt: int,
    retry_of: str | None = None,
) -> None:
    """Persist the outcome of one delivery attempt.

    Loads the row, mutates counters + sliding window, commits. Errors
    here are logged but never raised — we don't want a transient DB blip
    to crash the dispatcher background task.

    ``retry_of`` is set on records produced by the manual retry endpoint
    so the UI can render a "retry of <original>" badge.
    """
    try:
        async with session_factory() as db:
            row = (
                await db.execute(select(Webhook).where(Webhook.id == webhook_id))
            ).scalar_one_or_none()
            if row is None:
                # Hook deleted mid-flight; nothing to record.
                return

            row.last_fired_at = _dt.datetime.now(_dt.timezone.utc)
            row.last_status_code = status_code
            row.last_error = None if success else error

            if success:
                row.failure_count = 0
            else:
                row.failure_count = (row.failure_count or 0) + 1
                if row.failure_count >= AUTO_DISABLE_AFTER:
                    row.enabled = False
                    logger.warning(
                        "Webhook auto-disabled after %d consecutive failures",
                        row.failure_count,
                        extra={
                            "webhook_id": str(webhook_id),
                            "url": row.url,
                        },
                    )

            entry: dict[str, Any] = {
                "delivery_id": delivery_id,
                "event": event_type,
                "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "status_code": status_code,
                "error": error,
                "attempt": attempt,
                "success": success,
            }
            if retry_of is not None:
                entry["retry_of"] = retry_of
            row.recent_deliveries = _append_delivery_history(
                row.recent_deliveries,
                entry,
            )

            await db.commit()
    except Exception:  # noqa: BLE001 — best-effort persistence
        logger.exception(
            "Failed to record webhook delivery outcome",
            extra={"webhook_id": str(webhook_id)},
        )


# ---- The dispatcher ------------------------------------------------------- #


class WebhookDispatcher:
    """Subscriber of :data:`rp_server.events.event_bus` that fans events out
    to registered webhooks.

    Lifecycle: instantiate once at app startup, call :meth:`start` to spawn
    the subscriber task, and :meth:`stop` on shutdown. The dispatcher
    owns its own ``httpx.AsyncClient`` so we get connection pooling
    across deliveries — important when a single event matches many hooks.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        # The client is injected in tests so we can assert exactly what
        # the dispatcher would have POSTed without binding a real socket.
        self._http: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        self._owns_client: bool = http_client is None
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

    # -- public lifecycle -------------------------------------------------- #

    def start(self) -> None:
        """Spawn the bus-subscriber task.

        Idempotent — calling start twice is a no-op once a task is live.
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="webhook-dispatcher")
        logger.info("WebhookDispatcher started")

    async def stop(self) -> None:
        """Cancel the subscriber task and close the owned HTTP client."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._owns_client:
            await self._http.aclose()
        logger.info("WebhookDispatcher stopped")

    # -- the subscriber loop ---------------------------------------------- #

    async def _run(self) -> None:
        """Consume events and schedule a dispatch task per (event, hook)."""
        try:
            async for event_type, payload in event_bus.subscribe():
                # ``webhook.test`` events carry their target inline so we
                # don't have to scan the table for them — the admin
                # endpoint already knows which row to fire.
                if event_type == TEST_EVENT_TYPE and "_webhook_id" in payload:
                    target_id = payload.get("_webhook_id")
                    asyncio.create_task(
                        self._fire_test(target_id, payload),
                        name=f"webhook-test-{target_id}",
                    )
                    continue

                matches = await self._find_matches(event_type, payload)
                for hook_row in matches:
                    asyncio.create_task(
                        self._dispatch(hook_row, event_type, payload),
                        name=f"webhook-deliver-{hook_row['id']}",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("WebhookDispatcher loop crashed; will not restart")

    # -- DB query ---------------------------------------------------------- #

    async def _find_matches(
        self, event_type: str, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Return enabled hooks whose filters match this event.

        We materialise only the columns the dispatch path needs so the row
        is safe to use after the session closes (no lazy loads).
        """
        try:
            async with self._session_factory() as db:
                rows = (
                    (
                        await db.execute(
                            select(Webhook).where(Webhook.enabled.is_(True))
                        )
                    )
                    .scalars()
                    .all()
                )
                out: list[dict[str, Any]] = []
                for r in rows:
                    if not _event_matches_filter(event_type, list(r.event_filter or [])):
                        continue
                    if not _group_matches_filter(payload, list(r.group_filter or []) or None):
                        continue
                    out.append(
                        {
                            "id": r.id,
                            "url": r.url,
                            "secret": r.secret,
                        }
                    )
                return out
        except Exception:  # noqa: BLE001
            logger.exception(
                "Webhook match query failed",
                extra={"event_type": event_type},
            )
            return []

    # -- single delivery --------------------------------------------------- #

    async def _dispatch(
        self,
        hook: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        *,
        retry_of: str | None = None,
    ) -> None:
        """Deliver one event to one hook, with retries.

        ``retry_of`` is set by the manual retry endpoint to mark the
        produced record so the deliveries UI can render a "retry of
        <original-id>" badge. The wire payload itself is unchanged — the
        receiver only sees the new ``X-RP-Delivery-Id``.
        """
        delivery_id = str(uuid.uuid4())
        envelope, body = _build_delivery(
            event_type=event_type, payload=payload, delivery_id=delivery_id
        )
        signature = compute_signature(body, hook["secret"])
        headers = {
            "Content-Type": "application/json",
            "X-RP-Event-Type": event_type,
            "X-RP-Delivery-Id": delivery_id,
            "X-RP-Timestamp": envelope["timestamp"],
            "X-RP-Signature-256": signature,
        }

        last_status: int | None = None
        last_error: str | None = None
        success = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = RETRY_BACKOFF_SECONDS[attempt - 1]
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                resp = await self._http.post(
                    hook["url"], content=body, headers=headers
                )
                last_status = resp.status_code
                last_error = None
                if 200 <= resp.status_code < 300:
                    success = True
                    break
                last_error = f"HTTP {resp.status_code}"
            except httpx.RequestError as exc:
                last_status = None
                last_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001
                last_status = None
                last_error = f"{type(exc).__name__}: {exc}"

        if not success:
            logger.warning(
                "Webhook delivery failed after %d attempts",
                MAX_ATTEMPTS,
                extra={
                    "webhook_id": str(hook["id"]),
                    "event_type": event_type,
                    "last_status": last_status,
                    "last_error": last_error,
                },
            )

        await _record_result(
            self._session_factory,
            hook["id"],
            delivery_id=delivery_id,
            event_type=event_type,
            success=success,
            status_code=last_status,
            error=last_error,
            attempt=MAX_ATTEMPTS if not success else (attempt if success else MAX_ATTEMPTS),
            retry_of=retry_of,
        )

    # -- public manual retry ---------------------------------------------- #

    async def dispatch_retry(
        self,
        hook: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        *,
        retry_of: str,
    ) -> None:
        """Re-fire a previously recorded delivery payload.

        Thin wrapper over :meth:`_dispatch` so the admin retry endpoint
        doesn't have to reach for the private name. The original
        ``delivery_id`` is preserved via ``retry_of`` on the new record;
        the wire delivery gets a fresh ID (a retry is a new delivery
        from the receiver's POV).
        """
        await self._dispatch(hook, event_type, payload, retry_of=retry_of)

    # -- one-off test delivery (admin endpoint) --------------------------- #

    async def _fire_test(self, webhook_id: Any, payload: dict[str, Any]) -> None:
        """Fire a synthetic ``webhook.test`` at exactly one hook.

        Used by ``POST /v1/dash/webhooks/{id}/test``. We strip the
        internal ``_webhook_id`` marker before signing so the receiver
        sees a clean payload.
        """
        try:
            wid = uuid.UUID(str(webhook_id))
        except (TypeError, ValueError):
            logger.warning("Invalid webhook.test target id: %r", webhook_id)
            return

        try:
            async with self._session_factory() as db:
                row = (
                    await db.execute(select(Webhook).where(Webhook.id == wid))
                ).scalar_one_or_none()
                if row is None:
                    return
                hook = {"id": row.id, "url": row.url, "secret": row.secret}
        except Exception:  # noqa: BLE001
            logger.exception("Failed to load webhook for test fire")
            return

        clean_payload = {k: v for k, v in payload.items() if k != "_webhook_id"}
        await self._dispatch(hook, TEST_EVENT_TYPE, clean_payload)


# ---- Module-level singleton wiring --------------------------------------- #
#
# The dispatcher is instantiated in ``main.py``'s lifespan handler so it
# can share the same ``async_sessionmaker`` as the rest of the app. We
# expose a module-level slot so other code (notably the admin "test"
# endpoint, which needs to know the dispatcher exists at all) can opt in
# without dragging a FastAPI dependency through it.

_dispatcher: WebhookDispatcher | None = None


def set_dispatcher(d: WebhookDispatcher | None) -> None:
    """Register the active dispatcher (called from lifespan setup)."""
    global _dispatcher
    _dispatcher = d


def get_dispatcher() -> WebhookDispatcher | None:
    """Return the active dispatcher, or ``None`` if not initialised yet."""
    return _dispatcher
