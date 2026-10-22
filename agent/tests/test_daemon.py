"""Daemon supervision with fake loops, without network or commands."""

import asyncio
import signal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rp import daemon as module
from rp.daemon import HeartbeatDaemon


def daemon(monkeypatch):
    instance = HeartbeatDaemon.__new__(HeartbeatDaemon)
    instance.running = False
    instance._task = None
    instance.config = SimpleNamespace(
        host_id="test-host", heartbeat_interval_s=30, command_poll_interval_s=5
    )
    monkeypatch.setattr(instance, "_setup_signal_handlers", Mock())
    return instance


@pytest.mark.parametrize("failed_loop", ["_heartbeat_loop", "_command_loop"])
@pytest.mark.parametrize("termination", ["error", "return", "cancel"])
async def test_unexpected_loop_termination_fails_and_joins_sibling(
    monkeypatch, failed_loop, termination
):
    instance = daemon(monkeypatch)
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def sibling():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def failing():
        await entered.wait()
        if termination == "error":
            raise ValueError("simulated loop failure")
        if termination == "cancel":
            raise asyncio.CancelledError

    other = "_command_loop" if failed_loop == "_heartbeat_loop" else "_heartbeat_loop"
    monkeypatch.setattr(instance, failed_loop, failing)
    monkeypatch.setattr(instance, other, sibling)
    expected = ValueError if termination == "error" else RuntimeError
    with pytest.raises(expected):
        await asyncio.wait_for(instance.run(), timeout=1)
    assert cleaned.is_set()
    assert not instance.running


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
async def test_normal_signal_shutdown_does_not_report_loop_failure(monkeypatch, signum):
    instance = daemon(monkeypatch)
    handlers = {}
    monkeypatch.setattr(module.signal, "signal", lambda n, h: handlers.setdefault(n, h))
    monkeypatch.setattr(
        instance,
        "_setup_signal_handlers",
        instance.__class__._setup_signal_handlers.__get__(instance),
    )
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def sibling():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def shutdown():
        await entered.wait()
        handlers[signum](signum, None)
        assert not instance.running

    monkeypatch.setattr(instance, "_heartbeat_loop", shutdown)
    monkeypatch.setattr(instance, "_command_loop", sibling)
    await asyncio.wait_for(instance.run(), timeout=1)
    assert cleaned.is_set()
    assert not instance.running


async def test_external_cancellation_keeps_clean_exit_and_joins_both_loops(monkeypatch):
    instance = daemon(monkeypatch)
    entered = [asyncio.Event(), asyncio.Event()]
    cleaned = [asyncio.Event(), asyncio.Event()]

    def loop(index):
        async def wait():
            try:
                entered[index].set()
                await asyncio.Event().wait()
            finally:
                cleaned[index].set()

        return wait

    monkeypatch.setattr(instance, "_heartbeat_loop", loop(0))
    monkeypatch.setattr(instance, "_command_loop", loop(1))
    task = asyncio.create_task(instance.run())
    await asyncio.gather(*(event.wait() for event in entered))
    assert not task.done()
    task.cancel()
    await asyncio.wait_for(task, timeout=1)
    assert all(event.is_set() for event in cleaned)
    assert not instance.running


def test_main_daemon_does_not_swallow_loop_failure(monkeypatch):
    instance = daemon(monkeypatch)

    async def failing():
        raise ValueError("simulated loop failure")

    async def sibling():
        await asyncio.Event().wait()

    monkeypatch.setattr(instance, "_heartbeat_loop", failing)
    monkeypatch.setattr(instance, "_command_loop", sibling)
    monkeypatch.setattr(module, "HeartbeatDaemon", lambda: instance)
    with pytest.raises(ValueError):
        module.main_daemon()
