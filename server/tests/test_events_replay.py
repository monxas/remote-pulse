"""Unit tests for the SSE event-bus replay buffer (ADR-0009 polish).

The replay buffer is what powers ``Last-Event-ID``-driven gap recovery
in the SPA: every publish gets a monotonic id, the most recent N events
are retained, and a reconnecting subscriber can pull anything it
missed via :meth:`EventBus.replay_since`.
"""

from __future__ import annotations

import asyncio

import pytest

from rp_server.events import EventBus


@pytest.mark.asyncio
async def test_replay_returns_only_events_newer_than_last_id() -> None:
    bus = EventBus(replay_size=8)
    await bus.publish("host.heartbeat", {"i": 1})
    await bus.publish("host.heartbeat", {"i": 2})
    await bus.publish("host.heartbeat", {"i": 3})

    # The first publish got id=1, second=2, third=3. Asking for events
    # after id=1 returns the last two (in publish order).
    replay = bus.replay_since(1)
    assert [evt[2]["i"] for evt in replay] == [2, 3]


@pytest.mark.asyncio
async def test_replay_empty_when_no_newer_events() -> None:
    bus = EventBus(replay_size=8)
    await bus.publish("host.heartbeat", {"i": 1})
    assert bus.replay_since(1) == []
    # last_id=0 means "give me everything" — still works.
    replay = bus.replay_since(0)
    assert len(replay) == 1


@pytest.mark.asyncio
async def test_replay_buffer_caps_at_configured_size() -> None:
    bus = EventBus(replay_size=3)
    for i in range(5):
        await bus.publish("host.heartbeat", {"i": i})
    # Only the last 3 should be retained.
    replay = bus.replay_since(0)
    assert [evt[2]["i"] for evt in replay] == [2, 3, 4]


@pytest.mark.asyncio
async def test_subscribe_with_id_yields_monotonic_ids() -> None:
    bus = EventBus()
    received: list[tuple[int, str]] = []

    async def collect() -> None:
        async for event_id, event_type, _payload in bus.subscribe_with_id():
            received.append((event_id, event_type))
            if len(received) >= 2:
                return

    task = asyncio.create_task(collect())
    # Yield once so the subscriber's queue is registered.
    await asyncio.sleep(0)
    await bus.publish("a", {"x": 1})
    await bus.publish("b", {"x": 2})
    await asyncio.wait_for(task, timeout=1.0)

    assert [name for _, name in received] == ["a", "b"]
    # IDs must be strictly increasing.
    ids = [eid for eid, _ in received]
    assert ids[0] < ids[1]


@pytest.mark.asyncio
async def test_subscribe_back_compat_drops_id() -> None:
    """The legacy ``subscribe()`` shape (type, payload) is still honoured."""
    bus = EventBus()
    received: list[tuple[str, dict]] = []

    async def collect() -> None:
        async for event_type, payload in bus.subscribe():
            received.append((event_type, payload))
            return

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await bus.publish("legacy", {"x": "y"})
    await asyncio.wait_for(task, timeout=1.0)

    assert received == [("legacy", {"x": "y"})]
