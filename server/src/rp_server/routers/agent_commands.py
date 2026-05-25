"""Agent-pull endpoints for the command execution loop (Phase 2.5).

Closes the gap between command issuance/approval (handled by
``routers/commands.py`` + ``routers/approvals.py``) and actual execution
by the agent on the target host.

Flow
----
1. Operator issues a command via ``/v1/admin/commands`` (signed, possibly
   pending approval).
2. Approver clears it via ``/v1/admin/commands/approve/{token}`` (or it
   was created with ``human_approved=true``).
3. Agent on the target host polls ``GET /v1/agent/commands/pending`` every
   ``command_poll_interval_s`` (default 5s) and pulls any approved,
   not-yet-completed, not-stale commands assigned to it.
4. Agent executes locally and POSTs the result to
   ``POST /v1/agent/commands/{command_id}/result``.
5. Server records the outcome and fires a ``command.status_change`` SSE
   event so the dashboard updates in real time.

Authentication
--------------
Phase 2.5 trusts requests over the Tailscale mesh that carry a known
``host_id``. Caddy's public matcher allowlists these paths so the agent
doesn't need OIDC, and we assume the network layer (tailnet ACLs) is the
outer authentication boundary. The host_id existence check is a sanity
filter, not a security boundary.

TODO Phase 4: replace this with the per-host bearer token issued at
enrollment (the JWT signed by ``rp_server.auth.create_enrollment_token``).
The agent will send it in ``Authorization: Bearer …`` and the server will
verify host_id matches the ``sub`` claim. This must be combined with TLS
client cert or HMAC body signing for replay protection.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select, update

from rp_server.database import DbSession
from rp_server.events import fire_and_forget
from rp_server.models import Command, Host

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/agent", tags=["agent"])


# How far back to look for "fresh" approved commands. Anything older is
# treated as abandoned and won't be re-emitted to the agent. Matches the
# 1-hour window in the spec — gives operators ample time to approve via
# Telegram (5min token) and propagate to the agent (5s poll).
PENDING_WINDOW = timedelta(hours=1)

# Bytes cap mirrored on the agent side. We accept slightly more than the
# agent's 64 KiB cap because Pydantic counts characters, not bytes, and
# stderr can contain wide multibyte chars. The agent truncates first.
MAX_STREAM_BYTES = 128 * 1024


# ---- Schemas ----------------------------------------------------------- #


class PendingCommand(BaseModel):
    """Wire-format for a pending command handed to the agent."""

    id: uuid.UUID
    command_type: str
    command_payload: dict[str, Any]
    server_signature: str
    issued_at: datetime
    issued_by: str
    expires_at: datetime = Field(
        description=(
            "Best-effort expiry. Phase 2.5 derives this as issued_at + 1h "
            "since the actual signature expiry isn't persisted yet."
        )
    )


class PendingCommandsResponse(BaseModel):
    commands: list[PendingCommand]


class CommandResultPayload(BaseModel):
    """Agent → server execution outcome."""

    exit_code: int | None = Field(
        default=None,
        description="POSIX exit code; None for timeout / didn't run.",
    )
    stdout: str = Field(default="", max_length=MAX_STREAM_BYTES)
    stderr: str = Field(default="", max_length=MAX_STREAM_BYTES)
    duration_ms: int = Field(ge=0)
    agent_ts: datetime
    rejected_reason: str | None = Field(
        default=None,
        description="If the agent refused to execute (timeout, policy, etc.)",
    )


class CommandResultAck(BaseModel):
    ack: bool
    server_ts: datetime


# ---- Helpers ----------------------------------------------------------- #


async def _require_host(db: DbSession, host_id: uuid.UUID) -> Host:
    """Return host or raise 404 if unknown.

    TODO Phase 4: also verify the per-host bearer token here.
    """
    stmt = select(Host).where(Host.id == host_id)
    host = (await db.execute(stmt)).scalar_one_or_none()
    if host is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found",
        )
    return host


def _status_from_exit_code(exit_code: int | None, rejected_reason: str | None) -> str:
    """Map (exit_code, rejected_reason) → SSE status label.

    - exit_code == 0       → "succeeded"
    - exit_code != 0       → "failed"
    - exit_code is None    → "timeout" (or "rejected" if reason indicates so)
    """
    if exit_code == 0:
        return "succeeded"
    if exit_code is not None:
        return "failed"
    if rejected_reason and "timeout" in rejected_reason.lower():
        return "timeout"
    return "rejected" if rejected_reason else "timeout"


# ---- Endpoints --------------------------------------------------------- #


@router.get(
    "/commands/pending",
    response_model=PendingCommandsResponse,
)
async def list_pending_commands(
    db: DbSession,
    host_id: uuid.UUID = Query(..., description="UUID of the polling agent's host record"),
) -> PendingCommandsResponse:
    """Return commands the agent should execute, marking them as claimed.

    A command is "pending" when:
      - it's targeted at this host,
      - it has been approved (``human_approved=true``) **or** it was issued
        without an approval requirement (no token was attached),
      - it hasn't been rejected,
      - it hasn't already produced a result (``completed_at IS NULL``),
      - it was issued within ``PENDING_WINDOW`` (1h) so we don't re-emit
        stale items.

    Side effect: we stamp ``agent_node_id`` with the host_id of the puller
    so the audit log records who actually picked the command up. The
    operation is idempotent — re-polling within the same window returns
    the same rows (we don't transition out of "pending" until a result is
    posted), which keeps recovery simple if the agent crashes mid-run.

    Auth: Phase 2.5 trusts the tailnet. See module docstring TODO Phase 4.
    """
    host = await _require_host(db, host_id)

    cutoff = datetime.now(timezone.utc) - PENDING_WINDOW

    stmt = (
        select(Command)
        .where(
            and_(
                Command.host_id == host_id,
                Command.completed_at.is_(None),
                Command.rejected_reason.is_(None),
                # human_approved=True OR (no approval was ever required:
                # both token-related columns null → it was a plain issue).
                Command.human_approved.is_(True)
                | and_(
                    Command.approval_token.is_(None),
                    Command.approval_requested_at.is_(None),
                ),
                Command.issued_at >= cutoff,
            )
        )
        .order_by(Command.issued_at.asc())
    )

    rows = (await db.execute(stmt)).scalars().all()

    # Stamp agent_node_id for audit, but only when it's empty — preserve
    # first-claimer wins semantics. Use bulk UPDATE to bypass the Command
    # __setattr__ append-only guard (same pattern as approvals.py).
    claimable_ids = [c.id for c in rows if c.agent_node_id is None]
    if claimable_ids:
        await db.execute(
            update(Command)
            .where(Command.id.in_(claimable_ids))
            .values(agent_node_id=str(host_id))
        )
        await db.commit()

    logger.debug(
        "agent poll",
        host_id=str(host_id),
        hostname=host.hostname,
        pending_count=len(rows),
    )

    return PendingCommandsResponse(
        commands=[
            PendingCommand(
                id=c.id,
                command_type=c.command_type,
                command_payload=c.command_payload,
                server_signature=c.server_signature,
                issued_at=c.issued_at,
                issued_by=c.issued_by,
                # Phase 2.5: signature expiry isn't persisted on the row;
                # synthesise a generous bound so the agent can sanity-check.
                expires_at=c.issued_at + PENDING_WINDOW,
            )
            for c in rows
        ]
    )


@router.post(
    "/commands/{command_id}/result",
    response_model=CommandResultAck,
)
async def submit_command_result(
    command_id: uuid.UUID,
    payload: CommandResultPayload,
    db: DbSession,
    host_id: uuid.UUID = Query(
        ..., description="UUID of the reporting host (cross-checked against command.host_id)"
    ),
) -> CommandResultAck:
    """Record the agent's execution outcome and fan out an SSE event.

    Idempotency: the UPDATE includes ``completed_at IS NULL`` in its WHERE
    clause. A second submission from a retrying agent finds zero rows and
    returns 409 Conflict. The first writer wins.

    Auth: Phase 2.5 trusts the tailnet. We do verify that the supplied
    ``host_id`` matches the command's ``host_id`` so a misconfigured agent
    can't write to someone else's command record.
    """
    # Verify host exists (Phase 4 hook for bearer verification).
    await _require_host(db, host_id)

    # Cross-check: the host claiming this result must own the command.
    stmt = select(Command.host_id, Command.completed_at).where(Command.id == command_id)
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command {command_id} not found",
        )
    cmd_host_id, already_completed = row
    if cmd_host_id != host_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="host_id does not match command's target host",
        )
    if already_completed is not None:
        # Early 409 — avoids a guaranteed-zero UPDATE.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Command already has a recorded result",
        )

    now = datetime.now(timezone.utc)

    update_stmt = (
        update(Command)
        .where(
            and_(
                Command.id == command_id,
                Command.completed_at.is_(None),
            )
        )
        .values(
            exit_code=payload.exit_code,
            stdout=payload.stdout,
            stderr=payload.stderr,
            duration_ms=payload.duration_ms,
            completed_at=now,
            rejected_reason=payload.rejected_reason,
            agent_node_id=str(host_id),
        )
    )
    result = await db.execute(update_stmt)
    await db.commit()

    if result.rowcount == 0:
        # Lost the race with a concurrent submitter.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Command already has a recorded result",
        )

    status_label = _status_from_exit_code(payload.exit_code, payload.rejected_reason)

    logger.info(
        "command result recorded",
        command_id=str(command_id),
        host_id=str(host_id),
        exit_code=payload.exit_code,
        duration_ms=payload.duration_ms,
        status=status_label,
    )

    fire_and_forget(
        "command.status_change",
        {
            "command_id": str(command_id),
            "host_id": str(host_id),
            "status": status_label,
            "exit_code": payload.exit_code,
            "ts": now.isoformat(),
        },
    )

    return CommandResultAck(ack=True, server_ts=now)
