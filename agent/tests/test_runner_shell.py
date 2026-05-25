"""Tests for the Phase 2.5 shell-command runner.

These run actual /bin/sh subprocesses (the things they exercise — exit
codes, stderr capture, timeouts, output truncation — would all be lies
under mocking). They are POSIX-only; CI runs on Linux + macOS.
"""

from __future__ import annotations

import os
import sys

import pytest

from rp.commands.runner import (
    MAX_STREAM_BYTES,
    CommandResult,
    RemoteCommand,
    execute_remote_command,
)


pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="shell runner is POSIX-only in Phase 2.5"
)


def _cmd(command_type: str = "shell", payload: dict | None = None) -> RemoteCommand:
    return RemoteCommand(
        id="11111111-1111-1111-1111-111111111111",
        command_type=command_type,
        payload=payload or {},
        server_signature="sig-stub",
        issued_by="pytest",
        issued_at="2026-05-25T00:00:00+00:00",
    )


# ---- shell happy paths -----------------------------------------------------


async def test_shell_exit_zero_captures_stdout() -> None:
    result = await execute_remote_command(
        _cmd(payload={"cmd": "echo hello"})
    )
    assert isinstance(result, CommandResult)
    assert result.ack is True
    assert result.exit_code == 0
    assert (result.stdout or "").strip() == "hello"
    assert result.rejected_reason is None


async def test_shell_non_zero_exit_captures_stderr() -> None:
    result = await execute_remote_command(
        _cmd(payload={"cmd": "echo oops 1>&2; exit 7"})
    )
    assert result.ack is True
    assert result.exit_code == 7
    assert "oops" in (result.stderr or "")
    assert result.rejected_reason is None


# ---- timeout --------------------------------------------------------------


async def test_shell_timeout_returns_rejected_reason() -> None:
    result = await execute_remote_command(
        _cmd(payload={"cmd": "sleep 5", "timeout_s": 1})
    )
    assert result.ack is True
    assert result.exit_code is None
    assert result.rejected_reason == "timeout"
    assert "timeout" in (result.stderr or "").lower()


# ---- output capping -------------------------------------------------------


async def test_shell_stdout_truncated_to_64kib() -> None:
    # Emit ~150 KiB so we comfortably exceed the 64 KiB cap.
    cmd = "python3 -c \"import sys; sys.stdout.write('x' * (150*1024))\""
    result = await execute_remote_command(_cmd(payload={"cmd": cmd, "timeout_s": 10}))
    assert result.ack is True
    assert result.exit_code == 0
    encoded = (result.stdout or "").encode("utf-8")
    assert len(encoded) <= MAX_STREAM_BYTES, len(encoded)
    # And we kept the *tail* (last bytes are still x).
    assert encoded.endswith(b"x")


# ---- payload validation ---------------------------------------------------


async def test_shell_missing_cmd_rejected() -> None:
    result = await execute_remote_command(_cmd(payload={}))
    assert result.ack is False
    assert "cmd" in (result.rejected_reason or "")


async def test_shell_empty_cmd_rejected() -> None:
    result = await execute_remote_command(_cmd(payload={"cmd": "   "}))
    assert result.ack is False
    assert "cmd" in (result.rejected_reason or "")


async def test_shell_bad_timeout_type_rejected() -> None:
    result = await execute_remote_command(
        _cmd(payload={"cmd": "echo ok", "timeout_s": "not-an-int"})
    )
    assert result.ack is False
    assert "timeout_s" in (result.rejected_reason or "")


# ---- env hygiene ----------------------------------------------------------


async def test_shell_env_is_sanitised() -> None:
    """The subprocess should not inherit arbitrary parent env vars."""
    os.environ["RP_SHELL_LEAK_CHECK"] = "leaked"
    try:
        result = await execute_remote_command(
            _cmd(payload={"cmd": "printenv RP_SHELL_LEAK_CHECK || echo MISSING"})
        )
    finally:
        os.environ.pop("RP_SHELL_LEAK_CHECK", None)

    assert result.ack is True
    assert "MISSING" in (result.stdout or "")
    assert "leaked" not in (result.stdout or "")


# ---- unsupported command types -------------------------------------------


@pytest.mark.parametrize(
    "command_type", ["reboot", "ssh_rotate", "apt_update", "exec_script"]
)
async def test_unsupported_command_type_rejected(command_type: str) -> None:
    result = await execute_remote_command(_cmd(command_type=command_type))
    assert result.ack is False
    assert "not implemented" in (result.rejected_reason or "")
    assert command_type in (result.rejected_reason or "")


# ---- from_dict adapter ----------------------------------------------------


async def test_from_dict_accepts_command_payload_field() -> None:
    """Server emits ``command_payload``; the dataclass field is ``payload``."""
    cmd = RemoteCommand.from_dict(
        {
            "id": "abc",
            "command_type": "shell",
            "command_payload": {"cmd": "echo via_from_dict"},
            "server_signature": "sig",
            "issued_by": "u",
            "issued_at": "2026-05-25T00:00:00+00:00",
        }
    )
    assert cmd.payload == {"cmd": "echo via_from_dict"}
    result = await execute_remote_command(cmd)
    assert result.exit_code == 0
    assert "via_from_dict" in (result.stdout or "")
