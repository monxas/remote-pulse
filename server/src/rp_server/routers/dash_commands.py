"""JSON API for Commands + Approvals pages of the SvelteKit SPA (ADR-0009 Phase 2).

All endpoints live under ``/v1/dash/*`` and require an authenticated user
(``current_user`` dependency). Host-scoped queries are filtered by
``filter_hosts_by_user_groups`` so non-admin viewers only see their groups.

This router is a thin, cohesive layer over the existing admin commands /
approvals logic (``routers/commands.py`` + ``routers/approvals.py``). The SPA
calls these endpoints so it can stay inside the ``/v1/dash/*`` namespace,
while the underlying signing + immutability + Telegram flow stays in one
place.

Endpoints
---------
- ``GET    /v1/dash/commands``                              — paginated list
- ``POST   /v1/dash/commands``                              — issue (one per host)
- ``GET    /v1/dash/commands/{id}``                         — detail
- ``POST   /v1/dash/commands/{id}/retry``                   — reissue same payload
- ``GET    /v1/dash/approvals/pending``                     — pending approvals
- ``POST   /v1/dash/approvals/{id}/approve``                — approve (by command id)
- ``POST   /v1/dash/approvals/{id}/reject``                 — reject  (by command id)

See ADR-0009 §"Phase 2 — Commands + Approvals" for the full contract.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, update

from rp_server.database import DbSession
from rp_server.deps import current_user
from rp_server.events import fire_and_forget
from rp_server.models import Command, Host, User
from rp_server.permissions import user_has_permission
from rp_server.routers.commands import get_signing_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash", tags=["dash"])


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
APPROVAL_TTL_SECONDS = 300  # 5 minutes, matches approvals.py
DEFAULT_EXPIRES_IN_S = 60   # matches commands.py default

# Command types that always require human approval by policy.
# Operators can still override with explicit requires_approval=false on
# non-destructive types, but the SPA UI hints at this set.
REQUIRES_APPROVAL_BY_DEFAULT: frozenset[str] = frozenset(
    {"reboot", "ssh_rotate", "exec_script", "shell"}
)

# Status values surfaced to the dashboard. Derived from the existing
# columns on the commands table.
CommandStatus = Literal[
    "pending-approval",
    "approved",
    "queued",
    "running",
    "succeeded",
    "failed",
    "timeout",
    "rejected",
    "canceled",
]


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


class CommandIssueRequest(BaseModel):
    """Body for ``POST /v1/dash/commands``.

    One ``Command`` row will be created per ``host_id``. Approval policy:

    - ``requires_approval=True``  -> create command in ``pending-approval``
      state by assigning an ``approval_token``; an ``approval.created``
      event is emitted for live dashboards.
    - ``requires_approval=False`` -> create command in ``approved`` state
      (``human_approved=True``); ready for the agent to pick up on its
      next poll.
    - ``requires_approval=None``  -> apply the default policy from
      ``REQUIRES_APPROVAL_BY_DEFAULT``.
    """

    host_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    command_type: str = Field(min_length=1, max_length=50)
    command_payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=500)
    requires_approval: bool | None = Field(default=None)
    timeout_s: int = Field(default=300, ge=1, le=3600)
    expires_in_s: int = Field(default=DEFAULT_EXPIRES_IN_S, ge=10, le=300)


class CommandSummary(BaseModel):
    """Lean command row for the dashboard list/detail view."""

    id: uuid.UUID
    host_id: uuid.UUID
    host_hostname: str
    host_group: str | None
    issued_by: str
    command_type: str
    command_payload: dict[str, Any]
    status: CommandStatus
    issued_at: datetime
    completed_at: datetime | None
    exit_code: int | None
    duration_ms: int | None
    human_approved: bool
    approved_by: str | None
    rejected_reason: str | None
    approval_requested_at: datetime | None
    approval_responded_at: datetime | None
    stdout: str | None = None
    stderr: str | None = None


class CommandListResponse(BaseModel):
    commands: list[CommandSummary]
    next_cursor: str | None


class CommandIssueResponse(BaseModel):
    commands: list[CommandSummary]


class ApprovalActionRequest(BaseModel):
    """Body for approve/reject endpoints from the SPA."""

    reason: str | None = Field(default=None, max_length=500)


class ApprovalResult(BaseModel):
    status: Literal["approved", "rejected"]
    command_id: uuid.UUID
    message: str


class PendingApprovalItem(BaseModel):
    approval_id: uuid.UUID       # equal to command.id for the SPA's URL
    command_id: uuid.UUID
    command_type: str
    host_id: uuid.UUID
    host_hostname: str
    host_group: str | None
    issued_by: str
    issued_at: datetime
    approval_requested_at: datetime
    expires_at: datetime
    command_payload: dict[str, Any]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _classify_status(cmd: Command) -> CommandStatus:
    """Map raw command columns to the dashboard-facing status enum."""
    if cmd.rejected_reason:
        return "rejected"
    if cmd.completed_at is not None:
        # exit_code may be None for timeouts (agent never reported back)
        if cmd.exit_code is None:
            return "timeout"
        if cmd.exit_code == 0:
            return "succeeded"
        return "failed"
    if not cmd.human_approved:
        if cmd.approval_token is not None:
            return "pending-approval"
        # No approval requested, not approved, no completion → operator
        # decided to require approval but the flow hasn't been kicked off
        # yet. Surface as pending-approval so it doesn't masquerade as queued.
        return "pending-approval"
    # Approved and not completed → either queued waiting for poll, or
    # already running on the agent. We can't distinguish from columns alone
    # (no started_at), so surface "queued" until completion.
    return "queued"


def _to_summary(cmd: Command, host: Host) -> CommandSummary:
    return CommandSummary(
        id=cmd.id,
        host_id=cmd.host_id,
        host_hostname=host.hostname,
        host_group=host.group_name,
        issued_by=cmd.issued_by,
        command_type=cmd.command_type,
        command_payload=cmd.command_payload or {},
        status=_classify_status(cmd),
        issued_at=cmd.issued_at,
        completed_at=cmd.completed_at,
        exit_code=cmd.exit_code,
        duration_ms=cmd.duration_ms,
        human_approved=cmd.human_approved,
        approved_by=cmd.approved_by,
        rejected_reason=cmd.rejected_reason,
        approval_requested_at=cmd.approval_requested_at,
        approval_responded_at=cmd.approval_responded_at,
        stdout=cmd.stdout,
        stderr=cmd.stderr,
    )


def _encode_cursor(issued_at: datetime, cmd_id: uuid.UUID) -> str:
    """Opaque base64 cursor over ``(issued_at, id)`` — the list ordering key."""
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    raw = json.dumps({"ts": issued_at.isoformat(), "id": str(cmd_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode the opaque cursor → ``(issued_at, id)``. Raises 400 on garbage."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        ts = datetime.fromisoformat(data["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, uuid.UUID(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cursor: {exc}",
        ) from exc


def _filter_status(stmt, status_value: str):
    """Apply WHERE clauses to filter commands matching the dashboard status enum.

    Mirrors ``_classify_status`` but in SQL so we can paginate efficiently.
    """
    if status_value == "succeeded":
        return stmt.where(Command.completed_at.isnot(None), Command.exit_code == 0)
    if status_value == "failed":
        return stmt.where(
            Command.completed_at.isnot(None),
            Command.exit_code.isnot(None),
            Command.exit_code != 0,
        )
    if status_value == "timeout":
        return stmt.where(Command.completed_at.isnot(None), Command.exit_code.is_(None))
    if status_value == "rejected":
        return stmt.where(Command.rejected_reason.isnot(None))
    if status_value == "pending-approval":
        return stmt.where(
            Command.completed_at.is_(None),
            Command.rejected_reason.is_(None),
            Command.human_approved.is_(False),
        )
    if status_value == "approved":
        # "approved" here means "approved but not yet acknowledged complete"
        return stmt.where(
            Command.completed_at.is_(None),
            Command.rejected_reason.is_(None),
            Command.human_approved.is_(True),
        )
    if status_value in ("queued", "running"):
        # Same SQL shape as "approved" — we cannot distinguish from DB columns.
        return stmt.where(
            Command.completed_at.is_(None),
            Command.rejected_reason.is_(None),
            Command.human_approved.is_(True),
        )
    if status_value == "canceled":
        # No explicit "canceled" state in current schema. Reserved for future.
        return stmt.where(False)  # noqa: FBT003 — intentional empty result
    return stmt


def _scope_to_user_groups(stmt, user: User):
    """Restrict a Command query to hosts the user can see.

    Admin → no filter. Non-admin → join hosts and filter by accessible_groups.
    Non-admin with empty groups → empty result set.
    """
    if user.role == "admin":
        return stmt
    if not user.accessible_groups:
        return stmt.where(False)  # noqa: FBT003
    return stmt.join(Host, Command.host_id == Host.id).where(
        Host.group_name.in_(user.accessible_groups)
    )


# --------------------------------------------------------------------------- #
# GET /v1/dash/commands
# --------------------------------------------------------------------------- #


@router.get("/commands", response_model=CommandListResponse)
async def list_commands(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    status_filter: Annotated[
        str | None, Query(alias="status", description="One of the dashboard status values")
    ] = None,
    host_id: uuid.UUID | None = Query(default=None),
    issued_by: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None),
) -> CommandListResponse:
    """Cursor-paginated commands list for the SPA Commands page."""
    stmt = (
        select(Command, Host)
        .join(Host, Command.host_id == Host.id)
        .order_by(Command.issued_at.desc(), Command.id.desc())
    )

    # ACL: non-admin restricted by group
    if user.role != "admin":
        if not user.accessible_groups:
            return CommandListResponse(commands=[], next_cursor=None)
        stmt = stmt.where(Host.group_name.in_(user.accessible_groups))

    # Filters
    if status_filter:
        stmt = _filter_status(stmt, status_filter)
    if host_id is not None:
        stmt = stmt.where(Command.host_id == host_id)
    if issued_by:
        stmt = stmt.where(Command.issued_by == issued_by)

    # Cursor: take rows strictly past the cursor key (ts, id).
    if cursor:
        ts_after, id_after = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Command.issued_at < ts_after,
                and_(Command.issued_at == ts_after, Command.id < id_after),
            )
        )

    # +1 trick to know if there's another page
    stmt = stmt.limit(limit + 1)
    rows = (await db.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    summaries = [_to_summary(cmd, host) for cmd, host in rows]

    next_cursor: str | None = None
    if has_more and rows:
        last_cmd = rows[-1][0]
        next_cursor = _encode_cursor(last_cmd.issued_at, last_cmd.id)

    return CommandListResponse(commands=summaries, next_cursor=next_cursor)


# --------------------------------------------------------------------------- #
# GET /v1/dash/commands/{id}
# --------------------------------------------------------------------------- #


async def _load_command_for_user(
    db: DbSession, user: User, command_id: uuid.UUID
) -> tuple[Command, Host]:
    """Fetch a command with its host, applying group ACL. 404 if unseen."""
    stmt = select(Command, Host).join(Host, Command.host_id == Host.id).where(
        Command.id == command_id
    )
    if user.role != "admin":
        if not user.accessible_groups:
            raise HTTPException(status_code=404, detail="Command not found")
        stmt = stmt.where(Host.group_name.in_(user.accessible_groups))
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Command not found")
    return row[0], row[1]


@router.get("/commands/{command_id}", response_model=CommandSummary)
async def get_command(
    command_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> CommandSummary:
    cmd, host = await _load_command_for_user(db, user, command_id)
    return _to_summary(cmd, host)


# --------------------------------------------------------------------------- #
# POST /v1/dash/commands — issue one command per host_id
# --------------------------------------------------------------------------- #


async def _create_one_command(
    db: DbSession,
    *,
    user: User,
    host: Host,
    request: CommandIssueRequest,
    requires_approval: bool,
) -> Command:
    """Insert + sign one command row, handling the approval policy."""
    command_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.expires_in_s)

    payload = dict(request.command_payload or {})
    if request.reason and "reason" not in payload:
        payload["reason"] = request.reason

    signing_key = get_signing_key()
    signature = signing_key.sign_command(
        command_id=str(command_id),
        command_type=request.command_type,
        payload=payload,
        expires_at=expires_at,
    )

    now = datetime.now(timezone.utc)
    approval_token = uuid.uuid4() if requires_approval else None
    approval_requested_at = now if requires_approval else None

    cmd = Command(
        id=command_id,
        host_id=host.id,
        issued_by=user.email,
        command_type=request.command_type,
        command_payload=payload,
        server_signature=signature,
        human_approved=not requires_approval,
        approved_by=None if requires_approval else f"dash:{user.email}",
        approval_token=approval_token,
        approval_requested_at=approval_requested_at,
    )
    db.add(cmd)
    return cmd


@router.post(
    "/commands",
    response_model=CommandIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_command(
    body: CommandIssueRequest,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> CommandIssueResponse:
    """Issue a command to one or more hosts. Returns one command per host_id.

    Approval policy:
    - ``requires_approval`` not set → True if ``command_type`` is in
      ``REQUIRES_APPROVAL_BY_DEFAULT`` else False.
    - Operators (and admins) can override by setting it explicitly.

    Row-level ACL: admins bypass, everyone else needs the
    ``command.issue`` permission scoped to *every* host's ``group_name``
    (or ``*``). The check runs after the 404-for-missing-hosts guard so
    unknown / inaccessible hosts still yield 404, not 403 — but before
    any side-effect (sign + insert + SSE).
    """
    # ACL check + resolve hosts in one query
    host_ids = list(dict.fromkeys(body.host_ids))  # de-dup, preserve order
    stmt = select(Host).where(Host.id.in_(host_ids))
    if user.role != "admin":
        if not user.accessible_groups:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Host(s) not found or not accessible: {[str(h) for h in host_ids]}",
            )
        stmt = stmt.where(Host.group_name.in_(user.accessible_groups))
    hosts = (await db.execute(stmt)).scalars().all()
    by_id = {h.id: h for h in hosts}
    missing = [str(h) for h in host_ids if h not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host(s) not found or not accessible: {missing}",
        )

    # Row-level permission check — must pass for every host before we
    # mutate anything. Admins bypass via user_has_permission.
    for hid in host_ids:
        host = by_id[hid]
        if not await user_has_permission(
            db, user, "command.issue", host.group_name
        ):
            logger.warning(
                "command.issue denied by row-level ACL: user=%s role=%s "
                "host_id=%s host_group=%s",
                user.email,
                user.role,
                host.id,
                host.group_name,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Missing 'command.issue' permission for this host's group. "
                    "Ask an admin to grant it via Settings → Users → Permissions."
                ),
            )

    requires_approval = (
        body.requires_approval
        if body.requires_approval is not None
        else body.command_type in REQUIRES_APPROVAL_BY_DEFAULT
    )

    created: list[Command] = []
    for hid in host_ids:
        host = by_id[hid]
        cmd = await _create_one_command(
            db, user=user, host=host, request=body, requires_approval=requires_approval
        )
        created.append(cmd)

    await db.commit()
    for cmd in created:
        await db.refresh(cmd)

    # Re-load with host rows for response shape
    summaries: list[CommandSummary] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for cmd in created:
        host = by_id[cmd.host_id]
        summaries.append(_to_summary(cmd, host))

        # SSE: command.issued for every host
        fire_and_forget(
            "command.issued",
            {
                "command_id": str(cmd.id),
                "host_id": str(cmd.host_id),
                "group_name": host.group_name,
                "command_type": cmd.command_type,
                "issued_by": cmd.issued_by,
                "ts": now_iso,
            },
        )

        # SSE: approval.created if the command landed in pending-approval
        if cmd.approval_token is not None:
            fire_and_forget(
                "approval.created",
                {
                    "approval_id": str(cmd.id),
                    "command_id": str(cmd.id),
                    "command_type": cmd.command_type,
                    "host_id": str(cmd.host_id),
                    "group_name": host.group_name,
                    "issued_by": cmd.issued_by,
                    "ts": now_iso,
                },
            )

    logger.info(
        "dash issued commands",
        extra={
            "user": user.email,
            "command_type": body.command_type,
            "host_count": len(created),
            "requires_approval": requires_approval,
        },
    )

    return CommandIssueResponse(commands=summaries)


# --------------------------------------------------------------------------- #
# POST /v1/dash/commands/{id}/retry
# --------------------------------------------------------------------------- #


@router.post(
    "/commands/{command_id}/retry",
    response_model=CommandSummary,
    status_code=status.HTTP_201_CREATED,
)
async def retry_command(
    command_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> CommandSummary:
    """Reissue a command with the same type+payload against the same host.

    Row-level ACL: admins bypass, everyone else needs the
    ``command.issue`` permission scoped to the *original* command's host
    group (or ``*``). 404-for-unseen-command wins over 403 — we load the
    resource first so an operator who can't see a given command can't
    probe for its existence via the permission check.
    """
    orig, host = await _load_command_for_user(db, user, command_id)

    if not await user_has_permission(
        db, user, "command.issue", host.group_name
    ):
        logger.warning(
            "command.issue denied by row-level ACL on retry: user=%s role=%s "
            "command_id=%s host_group=%s",
            user.email,
            user.role,
            command_id,
            host.group_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Missing 'command.issue' permission for this host's group. "
                "Ask an admin to grant it via Settings → Users → Permissions."
            ),
        )

    requires_approval = orig.command_type in REQUIRES_APPROVAL_BY_DEFAULT

    request = CommandIssueRequest(
        host_ids=[host.id],
        command_type=orig.command_type,
        command_payload=orig.command_payload or {},
        reason=f"retry of {orig.id}",
        requires_approval=requires_approval,
    )
    cmd = await _create_one_command(
        db, user=user, host=host, request=request, requires_approval=requires_approval
    )
    await db.commit()
    await db.refresh(cmd)

    now_iso = datetime.now(timezone.utc).isoformat()
    fire_and_forget(
        "command.issued",
        {
            "command_id": str(cmd.id),
            "host_id": str(cmd.host_id),
            "group_name": host.group_name,
            "command_type": cmd.command_type,
            "issued_by": cmd.issued_by,
            "ts": now_iso,
        },
    )
    if cmd.approval_token is not None:
        fire_and_forget(
            "approval.created",
            {
                "approval_id": str(cmd.id),
                "command_id": str(cmd.id),
                "command_type": cmd.command_type,
                "host_id": str(cmd.host_id),
                "group_name": host.group_name,
                "issued_by": cmd.issued_by,
                "ts": now_iso,
            },
        )

    return _to_summary(cmd, host)


# --------------------------------------------------------------------------- #
# Approvals — wrappers over approvals.py for the SPA
# --------------------------------------------------------------------------- #


class PendingApprovalsResponse(BaseModel):
    """Wrapper to match the SPA's expected ``{ approvals: [...] }`` shape."""

    approvals: list[PendingApprovalItem]


@router.get("/approvals/pending", response_model=PendingApprovalsResponse)
async def list_pending_approvals(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> PendingApprovalsResponse:
    """Pending approvals visible to the caller (group-scoped)."""
    stmt = (
        select(Command, Host)
        .join(Host, Command.host_id == Host.id)
        .where(
            and_(
                Command.approval_token.isnot(None),
                Command.human_approved.is_(False),
                Command.rejected_reason.is_(None),
            )
        )
        .order_by(Command.approval_requested_at.desc().nullslast(), Command.issued_at.desc())
    )
    if user.role != "admin":
        if not user.accessible_groups:
            return []
        stmt = stmt.where(Host.group_name.in_(user.accessible_groups))

    items: list[PendingApprovalItem] = []
    for cmd, host in (await db.execute(stmt)).all():
        approval_requested_at = cmd.approval_requested_at or cmd.issued_at
        expires_at = approval_requested_at + timedelta(seconds=APPROVAL_TTL_SECONDS)
        items.append(
            PendingApprovalItem(
                approval_id=cmd.id,
                command_id=cmd.id,
                command_type=cmd.command_type,
                host_id=cmd.host_id,
                host_hostname=host.hostname,
                host_group=host.group_name,
                issued_by=cmd.issued_by,
                issued_at=cmd.issued_at,
                approval_requested_at=approval_requested_at,
                expires_at=expires_at,
                command_payload=cmd.command_payload or {},
            )
        )
    return PendingApprovalsResponse(approvals=items)


async def _resolve_approval(
    db: DbSession,
    user: User,
    approval_id: uuid.UUID,
    *,
    decision: Literal["approved", "rejected"],
    reason: str | None,
) -> tuple[Command, Host]:
    """Apply the approval decision atomically. ``approval_id == command.id``.

    Raises:
        404 if not visible, not pending, or already resolved.
        403 if caller lacks the ``command.approve`` permission for the
            command's host group (admins bypass — see
            :mod:`rp_server.permissions`).
    """
    cmd, host = await _load_command_for_user(db, user, approval_id)

    # Row-level ACL: admins bypass, everyone else needs ``command.approve``
    # scoped to the host's ``group_name`` (or ``*``). We check AFTER the
    # 404-leak guard above so unknown approvals still return 404, not 403.
    if not await user_has_permission(
        db, user, "command.approve", host.group_name
    ):
        logger.warning(
            "command.approve denied by row-level ACL: user=%s role=%s "
            "approval_id=%s host_group=%s",
            user.email,
            user.role,
            approval_id,
            host.group_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Missing 'command.approve' permission for this host's group. "
                "Ask an admin to grant it via Settings → Users → Permissions."
            ),
        )

    if cmd.completed_at is not None or cmd.rejected_reason is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Command already resolved",
        )
    if cmd.human_approved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Command already approved",
        )

    now = datetime.now(timezone.utc)
    if decision == "approved":
        # Atomic claim — guard against double-clicks / race with Telegram path.
        stmt = (
            update(Command)
            .where(
                and_(
                    Command.id == cmd.id,
                    Command.human_approved.is_(False),
                    Command.rejected_reason.is_(None),
                )
            )
            .values(
                human_approved=True,
                approved_by=f"dash:{user.email}",
                approval_responded_at=now,
                approval_token=None,
            )
        )
    else:
        text_reason = reason or "rejected via dashboard"
        stmt = (
            update(Command)
            .where(
                and_(
                    Command.id == cmd.id,
                    Command.human_approved.is_(False),
                    Command.rejected_reason.is_(None),
                )
            )
            .values(
                rejected_reason=f"dash:{user.email}:{text_reason}",
                approval_responded_at=now,
                approval_token=None,
            )
        )

    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Command was resolved by another request",
        )
    await db.commit()

    # Re-load to return fresh state
    fresh = (await db.execute(select(Command).where(Command.id == cmd.id))).scalar_one()
    return fresh, host


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResult)
async def approve_via_dash(
    approval_id: uuid.UUID,
    body: ApprovalActionRequest,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> ApprovalResult:
    """Approve a pending command. ``approval_id`` is the command id."""
    cmd, host = await _resolve_approval(
        db, user, approval_id, decision="approved", reason=body.reason
    )

    fire_and_forget(
        "approval.resolved",
        {
            "approval_id": str(cmd.id),
            "command_id": str(cmd.id),
            "resolution": "approved",
            "resolved_by": user.email,
            "reason": body.reason,
            "group_name": host.group_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )
    fire_and_forget(
        "command.status_change",
        {
            "command_id": str(cmd.id),
            "host_id": str(cmd.host_id),
            "group_name": host.group_name,
            "status": "approved",
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ApprovalResult(
        status="approved",
        command_id=cmd.id,
        message=f"Approved by {user.email}",
    )


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResult)
async def reject_via_dash(
    approval_id: uuid.UUID,
    body: ApprovalActionRequest,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> ApprovalResult:
    """Reject a pending command. ``approval_id`` is the command id."""
    cmd, host = await _resolve_approval(
        db, user, approval_id, decision="rejected", reason=body.reason
    )

    fire_and_forget(
        "approval.resolved",
        {
            "approval_id": str(cmd.id),
            "command_id": str(cmd.id),
            "resolution": "rejected",
            "resolved_by": user.email,
            "reason": body.reason,
            "group_name": host.group_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )
    fire_and_forget(
        "command.status_change",
        {
            "command_id": str(cmd.id),
            "host_id": str(cmd.host_id),
            "group_name": host.group_name,
            "status": "rejected",
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ApprovalResult(
        status="rejected",
        command_id=cmd.id,
        message=f"Rejected by {user.email}",
    )
