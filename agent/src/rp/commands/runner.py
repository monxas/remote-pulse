"""Remote command execution (Phase 2.5 — shell only).

This module is the agent-side entry point for commands pulled from
``GET /v1/agent/commands/pending``. The daemon's ``_command_loop`` calls
:func:`execute_remote_command` for each pending row and POSTs the result
back via ``POST /v1/agent/commands/{id}/result``.

Phase 2.5 scope
---------------
* ``shell`` command type: executed via ``subprocess.run("/bin/sh", "-c", ...)``
  with a configurable timeout (default 30s) and 64 KiB caps on stdout /
  stderr to avoid pathological memory blow-ups from misbehaving commands.
* Every other command type returns ``ack=False`` with a clean
  ``rejected_reason`` so the dashboard surfaces the unsupported call
  without the daemon crashing.

Phase 2.5 explicitly DOES NOT enforce signature verification or local
policy. That framework is sketched out in ``rp.signature`` /
``rp.local_policy`` / ``rp.replay_guard`` but requires production-grade
Ed25519 trust anchors, Telegram approval plumbing, and per-host policy
files that the v1.0 GA install flow doesn't yet provision. The server
is treated as trusted in Phase 2.5; defense-in-depth verification lands
in Phase 4 alongside the per-host bearer token rollout.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


# Cap on captured stdout / stderr before we hand the result to the server.
# Matches the server-side Pydantic ``max_length`` upper bound and keeps a
# rogue command (``yes`` etc.) from OOM-ing the agent VM.
MAX_STREAM_BYTES = 64 * 1024


@dataclass
class RemoteCommand:
    """Remote command pulled from the server.

    The server-side schema (PendingCommand) sends ``command_payload``;
    older agent code referred to this as ``payload``. We accept both via
    :py:meth:`from_dict` to keep the wire shape compatible.
    """

    id: str
    command_type: str
    payload: dict[str, Any]
    server_signature: str
    issued_by: str
    issued_at: str
    expires_at: Optional[datetime] = None
    # Kept for legacy callers; not populated by the Phase 2.5 server.
    target_group: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemoteCommand":
        """Build from the wire format emitted by /v1/agent/commands/pending."""
        return cls(
            id=str(data["id"]),
            command_type=data["command_type"],
            # Server uses ``command_payload``; tolerate ``payload`` for
            # backwards-compat with the old runner stub.
            payload=data.get("command_payload") or data.get("payload") or {},
            server_signature=data.get("server_signature", ""),
            issued_by=data.get("issued_by", ""),
            issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at"),
            target_group=data.get("target_group"),
        )


@dataclass
class CommandResult:
    """Result of command execution, headed back to the server."""

    ack: bool
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    rejected_reason: Optional[str] = None


def _truncate(s: str, limit: int = MAX_STREAM_BYTES) -> str:
    """Truncate a stream to ``limit`` bytes, keeping the tail.

    We prefer the tail because that's where the interesting failure
    information typically is (final error, traceback, etc.).
    """
    if not s:
        return ""
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return s
    return encoded[-limit:].decode("utf-8", errors="replace")


def _run_shell(payload: dict[str, Any]) -> CommandResult:
    """Execute ``payload['cmd']`` under /bin/sh with a hard timeout.

    Payload schema::

        {"cmd": "<string>", "timeout_s": <int, default 30>}

    The subprocess inherits no environment except a sanitised ``PATH``
    so commands behave predictably across distros / shells.
    """
    cmd_str = payload.get("cmd")
    if not isinstance(cmd_str, str) or not cmd_str.strip():
        return CommandResult(
            ack=False,
            rejected_reason="invalid_payload: missing or empty 'cmd'",
        )

    timeout = payload.get("timeout_s", 30)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return CommandResult(
            ack=False, rejected_reason="invalid_payload: 'timeout_s' must be int"
        )
    if timeout <= 0 or timeout > 3600:
        return CommandResult(
            ack=False,
            rejected_reason="invalid_payload: 'timeout_s' out of range (1..3600)",
        )

    try:
        proc = subprocess.run(
            ["/bin/sh", "-c", cmd_str],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG": "C.UTF-8",
            },
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("shell command timed out", timeout_s=timeout)
        # subprocess sets stdout/stderr to bytes-or-None when text=True
        # with a timeout; coerce to str defensively.
        return CommandResult(
            ack=True,
            exit_code=None,
            stdout=_truncate(exc.stdout if isinstance(exc.stdout, str) else ""),
            stderr=_truncate(
                (exc.stderr if isinstance(exc.stderr, str) else "")
                + f"\ntimeout after {timeout}s"
            ),
            rejected_reason="timeout",
        )
    except OSError as exc:
        logger.error("shell exec failed", error=str(exc))
        return CommandResult(
            ack=False,
            rejected_reason=f"exec_error: {exc!s}",
        )

    return CommandResult(
        ack=True,
        exit_code=proc.returncode,
        stdout=_truncate(proc.stdout or ""),
        stderr=_truncate(proc.stderr or ""),
    )


async def execute_remote_command(cmd: RemoteCommand) -> CommandResult:
    """Dispatch a remote command to its type-specific runner.

    Phase 2.5: only ``shell`` is implemented; every other type returns a
    clean rejection so the dashboard can show "not implemented" without
    the daemon crashing.

    TODO Phase 4: re-introduce ``ServerTrust.verify_command`` + the
    ``LocalPolicy`` evaluation that used to live here (see git history).
    Those layers need a working trust-anchor distribution and Telegram
    approval flow first.
    """
    logger.info(
        "executing remote command",
        cmd_id=cmd.id,
        command_type=cmd.command_type,
        issued_by=cmd.issued_by,
    )

    if cmd.command_type == "shell":
        return _run_shell(cmd.payload)

    return CommandResult(
        ack=False,
        rejected_reason=(
            f"command_type '{cmd.command_type}' not implemented in v1.0"
        ),
    )
