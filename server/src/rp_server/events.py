"""In-process event bus for Server-Sent Events fan-out (ADR-0009 Phase 1).

Provides a singleton publish/subscribe bus that lets request handlers
(heartbeat, command, approval) push events to long-lived SSE connections
in the same process.

Phase 1 limitation
------------------
The bus is **per-process**. Remote-Pulse server runs with multiple Uvicorn
workers (typically 2), and each worker has its own ``EventBus`` instance.
That means a heartbeat received by worker A will only be visible to SSE
clients connected to worker A. Worker affinity is handled by Caddy's
upstream load balancing.

Replay buffer (ADR-0009 polish)
-------------------------------
Every publish is assigned a monotonic integer id and the most recent
``replay_size`` events are retained in an in-memory deque. The SSE stream
endpoint reads ``Last-Event-ID`` on reconnect and replays events with
ids strictly greater than that value as a synthetic ``gap`` event before
streaming live traffic. The buffer is per-process and best-effort — a
client that misses more than ``replay_size`` events while disconnected
just doesn't get a replay (the polling fallback still catches the SPA
up via cache invalidation when the connection recovers).

TODO (Phase 2+): swap the in-process queue for Redis pub/sub (or NATS) so
events fan out across workers, and so we can horizontally scale the API
without breaking real-time updates. Until then, the dashboard tolerates
the gap by polling ``/v1/dash/overview`` every 5s as a backstop.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """Per-process pub/sub bus for SSE fan-out.

    Each subscriber gets its own bounded ``asyncio.Queue``. Slow subscribers
    that fill their queue silently drop events (logged at WARNING) — we do
    NOT block the publisher because the heartbeat hot path must never wait
    on a stalled SSE client.

    Publishes are tagged with a monotonic integer id and a copy of the
    most recent ``replay_size`` events is kept so reconnecting subscribers
    can request a gap replay via ``Last-Event-ID``.
    """

    def __init__(self, max_queue_size: int = 256, replay_size: int = 128) -> None:
        self._subscribers: set[asyncio.Queue[tuple[int, str, dict[str, Any]]]] = set()
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
        self._id_counter = itertools.count(1)
        self._replay: deque[tuple[int, str, dict[str, Any]]] = deque(maxlen=replay_size)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to every active subscriber.

        Non-blocking: drops events on full queues rather than back-pressuring
        the caller. Safe to call from request handlers.
        """
        event_id = next(self._id_counter)
        item = (event_id, event_type, payload)
        # Record into replay buffer first so a slow subscriber that just
        # connected doesn't miss the event entirely if its queue is full.
        self._replay.append(item)

        async with self._lock:
            # Snapshot to iterate without holding the lock across awaits
            # (publishers are sync once the queue is grabbed).
            subscribers = list(self._subscribers)

        if not subscribers:
            return

        for queue in subscribers:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE subscriber queue full, dropping event",
                    extra={"event_type": event_type, "max_queue_size": self._max_queue_size},
                )

    async def subscribe(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield ``(event_type, payload)`` forever; cancel to unsubscribe.

        Back-compat shim — callers that need the monotonic event id
        should use :meth:`subscribe_with_id` instead. Kept on the same
        bounded queue so existing publishers keep their drop-on-full
        semantics unchanged.
        """
        async for _, event_type, payload in self.subscribe_with_id():
            yield event_type, payload

    async def subscribe_with_id(self) -> AsyncIterator[tuple[int, str, dict[str, Any]]]:
        """Yield ``(event_id, event_type, payload)`` forever.

        Typical use::

            async for event_id, event_type, payload in event_bus.subscribe_with_id():
                yield {"id": event_id, "event": event_type, "data": json.dumps(payload)}

        The async iterator's ``aclose()`` (called when the consumer task
        is cancelled / the generator is garbage-collected) removes the
        queue from the subscriber set.
        """
        queue: asyncio.Queue[tuple[int, str, dict[str, Any]]] = asyncio.Queue(
            maxsize=self._max_queue_size
        )

        async with self._lock:
            self._subscribers.add(queue)
        logger.debug(
            "SSE subscriber attached",
            extra={"subscriber_count": len(self._subscribers)},
        )

        try:
            while True:
                event_id, event_type, payload = await queue.get()
                yield event_id, event_type, payload
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
            logger.debug(
                "SSE subscriber detached",
                extra={"subscriber_count": len(self._subscribers)},
            )

    def replay_since(self, last_id: int) -> list[tuple[int, str, dict[str, Any]]]:
        """Return all buffered events with id strictly greater than ``last_id``.

        Returns an empty list if the buffer has rolled past ``last_id``
        (i.e. the gap is too wide to replay reliably); the SSE endpoint
        will still send an empty ``gap`` event so the client at least
        knows replay was attempted.
        """
        return [item for item in self._replay if item[0] > last_id]

    @property
    def subscriber_count(self) -> int:
        """Current number of active subscribers (for diagnostics/metrics)."""
        return len(self._subscribers)


# Process-wide singleton. Imported by routers and the SSE endpoint alike.
event_bus = EventBus()


def fire_and_forget(event_type: str, payload: dict[str, Any]) -> None:
    """Publish an event without awaiting — for use in hot paths (heartbeat).

    Schedules the publish as a background task so the caller doesn't pay
    the lock + fan-out cost. If no event loop is running (e.g. during
    tests that don't drive the loop) we silently no-op.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(event_bus.publish(event_type, payload))
