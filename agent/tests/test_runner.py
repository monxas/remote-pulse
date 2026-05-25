"""Tests for remote command runner contract (Phase 2.5).

Phase 2.5 deliberately bypasses the older Ed25519 signature + local-policy
+ Telegram-approval layers (those will return in Phase 4 alongside the
per-host bearer rollout). The runner is now a thin type-dispatcher:

  * ``shell`` is implemented via subprocess (see test_runner_shell.py).
  * Every other type returns ``ack=False`` with a clean ``rejected_reason``.

These tests pin the *contract* — that the runner doesn't crash on the
non-shell types and that the rejection message is informative enough for
the dashboard to show.
"""

from __future__ import annotations

import pytest

from rp.commands.runner import RemoteCommand, execute_remote_command


def _cmd(command_type: str, payload: dict | None = None) -> RemoteCommand:
    return RemoteCommand(
        id=f"test-{command_type}",
        command_type=command_type,
        payload=payload or {},
        server_signature="fake-sig",
        issued_by="test-user",
        issued_at="2026-05-25T00:00:00+00:00",
        target_group="prod",
    )


@pytest.mark.asyncio
async def test_runner_rejects_exec_shell_legacy_type() -> None:
    """The old ``exec_shell`` type isn't part of the Phase 2.5 surface — use ``shell``."""
    result = await execute_remote_command(_cmd("exec_shell"))
    assert result.ack is False
    assert "not implemented" in (result.rejected_reason or "")


@pytest.mark.asyncio
async def test_runner_rejects_pkg_install() -> None:
    result = await execute_remote_command(_cmd("pkg_install", {"name": "nginx"}))
    assert result.ack is False
    assert "not implemented" in (result.rejected_reason or "")


@pytest.mark.asyncio
async def test_runner_rejects_screen_open() -> None:
    result = await execute_remote_command(
        _cmd("screen_open", {"protocol": "rustdesk"})
    )
    assert result.ack is False
    assert "not implemented" in (result.rejected_reason or "")
    assert "screen_open" in (result.rejected_reason or "")


@pytest.mark.asyncio
async def test_runner_executes_shell_type() -> None:
    """The one type we do implement actually runs."""
    result = await execute_remote_command(_cmd("shell", {"cmd": "true"}))
    assert result.ack is True
    assert result.exit_code == 0
