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

TODO (Phase 2+): swap the in-process queue for Redis pub/sub (or NATS) so
events fan out across workers, and so we can horizontally scale the API
without breaking real-time updates. Until then, the dashboard tolerates
the gap by polling ``/v1/dash/overview`` every 5s as a backstop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """Per-process pub/sub bus for SSE fan-out.

    Each subscriber gets its own bounded ``asyncio.Queue``. Slow subscribers
    that fill their queue silently drop events (logged at WARNING) — we do
    NOT block the publisher because the heartbeat hot path must never wait
    on a stalled SSE client.
    """

    def __init__(self, max_queue_size: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = set()
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to every active subscriber.

        Non-blocking: drops events on full queues rather than back-pressuring
        the caller. Safe to call from request handlers.
        """
        async with self._lock:
            # Snapshot to iterate without holding the lock across awaits
            # (publishers are sync once the queue is grabbed).
            subscribers = list(self._subscribers)

        if not subscribers:
            return

        item = (event_type, payload)
        for queue in subscribers:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE subscriber queue full, dropping event",
                    extra={"event_type": event_type, "max_queue_size": self._max_queue_size},
                )

    async def subscribe(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield events forever; cancel the consuming task to unsubscribe.

        Typical use::

            async for event_type, payload in event_bus.subscribe():
                yield {"event": event_type, "data": json.dumps(payload)}

        The async iterator's ``aclose()`` (called when the consumer task
        is cancelled / the generator is garbage-collected) removes the
        queue from the subscriber set.
        """
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(
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
                event_type, payload = await queue.get()
                yield event_type, payload
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
            logger.debug(
                "SSE subscriber detached",
                extra={"subscriber_count": len(self._subscribers)},
            )

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
