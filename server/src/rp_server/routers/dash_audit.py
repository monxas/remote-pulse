"""Synthetic audit-timeline endpoint for the SvelteKit SPA (ADR-0009 Phase 2).

There is no dedicated ``audit_logs`` table in Remote-Pulse — every operationally
interesting event is already captured in one of the existing tables:

============================================================================
event                       table         when
----------------------------------------------------------------------------
command.issued              commands      issued_at
command.approved            commands      approval_responded_at + human_approved
command.rejected            commands      approval_responded_at + rejected_reason
command.completed           commands      completed_at + exit_code == 0
command.failed              commands      completed_at + exit_code != 0
host.enrolled               hosts         enrolled_at
enrollment.token_issued     enrollments   created_at
============================================================================

This router exposes them as one normalised timeline, paginated by
``(ts DESC, src, id)``. The implementation builds a single SQL ``UNION ALL``
so no matter how many sources we add later it stays one round-trip.

All host-scoped events are filtered by the caller's ``accessible_groups``.
Events without a host context (token issuance) only land in the timeline
for ``admin`` callers.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    column,
    literal,
    literal_column,
    or_,
    select,
    union_all,
)

from rp_server.database import DbSession
from rp_server.deps import current_user
from rp_server.models import AuditEvent as AuditEventRow
from rp_server.models import Command, Enrollment, Host, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash", tags=["dash"])


DEFAULT_LIMIT = 50
MAX_LIMIT = 200

AuditAction = Literal[
    "command.issued",
    "command.approved",
    "command.rejected",
    "command.completed",
    "command.failed",
    "host.enrolled",
    "enrollment.token_issued",
    "settings.group.create",
    "settings.group.delete",
    "settings.user.create",
    "settings.user.update",
    "settings.user.delete",
]

AuditTargetType = Literal["command", "host", "enrollment", "user", "group"]


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


class AuditEvent(BaseModel):
    id: str  # synthetic — "<src>:<pk>", stable per (action, target_id)
    ts: datetime
    actor: str
    action: AuditAction
    target_type: AuditTargetType
    # ``str`` rather than ``uuid.UUID``: group resource ids are names
    # (groups.name is the PK and may contain dots/dashes), so we widen the
    # field. UUID-valued targets are still serialised as UUID strings, which
    # the SvelteKit client already treats as opaque strings.
    target_id: str
    target_label: str
    metadata: dict[str, Any]


class AuditResponse(BaseModel):
    events: list[AuditEvent]
    next_cursor: str | None


# --------------------------------------------------------------------------- #
# Cursor — (ts, src, id) lexicographic
# --------------------------------------------------------------------------- #


def _encode_cursor(ts: datetime, src: str, row_id: str) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    raw = json.dumps(
        {"ts": ts.isoformat(), "src": src, "id": row_id}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        ts = datetime.fromisoformat(data["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, str(data["src"]), str(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cursor: {exc}",
        ) from exc


# --------------------------------------------------------------------------- #
# Source SELECTs — each produces the same 7-column shape
# --------------------------------------------------------------------------- #
#
# Columns (in fixed order):
#   ts          TIMESTAMPTZ
#   src         TEXT      — short tag used for cursor ordering + id prefix
#   action      TEXT
#   target_type TEXT
#   target_id   TEXT      — UUID cast to text; SQLite-friendly
#   actor       TEXT
#   group_name  TEXT|NULL — for ACL filter
#   label       TEXT      — human-friendly summary
#   pk          TEXT      — source row PK as text (for id_after tie-break)
#
# We add a leading literal column ``src`` so SQLAlchemy's UNION ALL doesn't
# mis-align dialect-specific column ordering.


def _commands_issued_select():
    return (
        select(
            Command.issued_at.label("ts"),
            literal("cmd_issued").label("src"),
            literal("command.issued").label("action"),
            literal("command").label("target_type"),
            cast(Command.id, String).label("target_id"),
            Command.issued_by.label("actor"),
            Host.group_name.label("group_name"),
            (Command.command_type + literal(" on ") + Host.hostname).label("label"),
            cast(Command.id, String).label("pk"),
        )
        .join(Host, Command.host_id == Host.id)
    )


def _commands_approved_select():
    return (
        select(
            Command.approval_responded_at.label("ts"),
            literal("cmd_approved").label("src"),
            literal("command.approved").label("action"),
            literal("command").label("target_type"),
            cast(Command.id, String).label("target_id"),
            # approved_by may be null if old data; fall back to issued_by
            case(
                (Command.approved_by.isnot(None), Command.approved_by),
                else_=Command.issued_by,
            ).label("actor"),
            Host.group_name.label("group_name"),
            (literal("approved ") + Command.command_type + literal(" on ") + Host.hostname).label(
                "label"
            ),
            cast(Command.id, String).label("pk"),
        )
        .join(Host, Command.host_id == Host.id)
        .where(
            and_(
                Command.approval_responded_at.isnot(None),
                Command.human_approved.is_(True),
            )
        )
    )


def _commands_rejected_select():
    return (
        select(
            Command.approval_responded_at.label("ts"),
            literal("cmd_rejected").label("src"),
            literal("command.rejected").label("action"),
            literal("command").label("target_type"),
            cast(Command.id, String).label("target_id"),
            case(
                (Command.approved_by.isnot(None), Command.approved_by),
                else_=Command.issued_by,
            ).label("actor"),
            Host.group_name.label("group_name"),
            (literal("rejected ") + Command.command_type + literal(" on ") + Host.hostname).label(
                "label"
            ),
            cast(Command.id, String).label("pk"),
        )
        .join(Host, Command.host_id == Host.id)
        .where(
            and_(
                Command.approval_responded_at.isnot(None),
                Command.rejected_reason.isnot(None),
            )
        )
    )


def _commands_completed_select():
    return (
        select(
            Command.completed_at.label("ts"),
            literal("cmd_done").label("src"),
            literal("command.completed").label("action"),
            literal("command").label("target_type"),
            cast(Command.id, String).label("target_id"),
            literal("system").label("actor"),
            Host.group_name.label("group_name"),
            (literal("succeeded ") + Command.command_type + literal(" on ") + Host.hostname).label(
                "label"
            ),
            cast(Command.id, String).label("pk"),
        )
        .join(Host, Command.host_id == Host.id)
        .where(and_(Command.completed_at.isnot(None), Command.exit_code == 0))
    )


def _commands_failed_select():
    return (
        select(
            Command.completed_at.label("ts"),
            literal("cmd_fail").label("src"),
            literal("command.failed").label("action"),
            literal("command").label("target_type"),
            cast(Command.id, String).label("target_id"),
            literal("system").label("actor"),
            Host.group_name.label("group_name"),
            (literal("failed ") + Command.command_type + literal(" on ") + Host.hostname).label(
                "label"
            ),
            cast(Command.id, String).label("pk"),
        )
        .join(Host, Command.host_id == Host.id)
        .where(
            and_(
                Command.completed_at.isnot(None),
                Command.exit_code.isnot(None),
                Command.exit_code != 0,
            )
        )
    )


def _hosts_enrolled_select():
    return select(
        Host.enrolled_at.label("ts"),
        literal("host_enroll").label("src"),
        literal("host.enrolled").label("action"),
        literal("host").label("target_type"),
        cast(Host.id, String).label("target_id"),
        literal("system").label("actor"),
        Host.group_name.label("group_name"),
        (literal("enrolled ") + Host.hostname).label("label"),
        cast(Host.id, String).label("pk"),
    )


def _enrollment_tokens_select():
    return select(
        Enrollment.created_at.label("ts"),
        literal("enroll_tok").label("src"),
        literal("enrollment.token_issued").label("action"),
        literal("enrollment").label("target_type"),
        cast(Enrollment.id, String).label("target_id"),
        Enrollment.issued_by.label("actor"),
        Enrollment.group_name.label("group_name"),
        (literal("token for group ") + Enrollment.group_name).label("label"),
        cast(Enrollment.id, String).label("pk"),
    )


# --------------------------------------------------------------------------- #
# Real audit_events rows — one source SELECT per action. We split by action
# (rather than one generic select) so the dispatcher's ``selected_actions``
# filter Just Works without a second WHERE on action against the union.
# --------------------------------------------------------------------------- #


def _audit_events_source(action: str, target_type: str, src: str):
    """Build a 9-column SELECT over ``audit_events`` filtered to a single action.

    Resource ids are already stored as TEXT, so no cast. ``group_name`` is
    NULL — settings events aren't ACL-scoped today (admins only), but we
    surface the resource_id in ``label`` so the timeline reads cleanly.
    """
    return (
        select(
            AuditEventRow.ts.label("ts"),
            literal(src).label("src"),
            literal(action).label("action"),
            literal(target_type).label("target_type"),
            AuditEventRow.resource_id.label("target_id"),
            AuditEventRow.actor.label("actor"),
            literal(None, type_=String).label("group_name"),
            (literal(f"{action} ") + AuditEventRow.resource_id).label("label"),
            cast(AuditEventRow.id, String).label("pk"),
        )
        .where(AuditEventRow.action == action)
    )


def _settings_group_create_select():
    return _audit_events_source("settings.group.create", "group", "set_g_new")


def _settings_group_delete_select():
    return _audit_events_source("settings.group.delete", "group", "set_g_del")


def _settings_user_create_select():
    return _audit_events_source("settings.user.create", "user", "set_u_new")


def _settings_user_update_select():
    return _audit_events_source("settings.user.update", "user", "set_u_upd")


def _settings_user_delete_select():
    return _audit_events_source("settings.user.delete", "user", "set_u_del")


_ALL_SOURCES = {
    "command.issued":            _commands_issued_select,
    "command.approved":          _commands_approved_select,
    "command.rejected":          _commands_rejected_select,
    "command.completed":         _commands_completed_select,
    "command.failed":            _commands_failed_select,
    "host.enrolled":             _hosts_enrolled_select,
    "enrollment.token_issued":   _enrollment_tokens_select,
    "settings.group.create":     _settings_group_create_select,
    "settings.group.delete":     _settings_group_delete_select,
    "settings.user.create":      _settings_user_create_select,
    "settings.user.update":      _settings_user_update_select,
    "settings.user.delete":      _settings_user_delete_select,
}

# Map action → target_type so we can short-circuit when target_type filter is
# given without an action filter.
_TARGET_TYPE_BY_ACTION: dict[str, str] = {
    "command.issued": "command",
    "command.approved": "command",
    "command.rejected": "command",
    "command.completed": "command",
    "command.failed": "command",
    "host.enrolled": "host",
    "enrollment.token_issued": "enrollment",
    "settings.group.create": "group",
    "settings.group.delete": "group",
    "settings.user.create": "user",
    "settings.user.update": "user",
    "settings.user.delete": "user",
}


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


@router.get("/audit", response_model=AuditResponse)
async def list_audit_events(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    actor: str | None = Query(default=None, max_length=255),
    action: str | None = Query(default=None, max_length=64),
    target_type: str | None = Query(default=None, max_length=32),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None),
) -> AuditResponse:
    """Unified audit timeline. Single UNION ALL query, cursor paginated."""

    # Decide which source sub-queries to include.
    selected_actions: list[str] = list(_ALL_SOURCES.keys())
    if action:
        if action not in _ALL_SOURCES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown action '{action}'",
            )
        selected_actions = [action]
    if target_type:
        if target_type not in {"command", "host", "enrollment", "user", "group"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown target_type '{target_type}'",
            )
        selected_actions = [
            a for a in selected_actions if _TARGET_TYPE_BY_ACTION.get(a) == target_type
        ]
    if not selected_actions:
        return AuditResponse(events=[], next_cursor=None)

    # Cursor decode
    cursor_ts: datetime | None = None
    cursor_src: str | None = None
    cursor_pk: str | None = None
    if cursor:
        cursor_ts, cursor_src, cursor_pk = _decode_cursor(cursor)

    # Build each source SELECT, then apply the common filters in the outer
    # query so we don't repeat them N times. We keep WHERE clauses that
    # reference source-specific columns (group_name on Host vs Enrollment)
    # inside the source SELECT factories themselves — but actor/since/until
    # all live on the shared output columns so we wrap with a subquery.
    subqueries = [_ALL_SOURCES[a]() for a in selected_actions]
    union_q = union_all(*subqueries).subquery("audit_union")

    # Reference the union's columns by name.
    ts_c = union_q.c.ts
    src_c = union_q.c.src
    action_c = union_q.c.action
    target_type_c = union_q.c.target_type
    target_id_c = union_q.c.target_id
    actor_c = union_q.c.actor
    group_c = union_q.c.group_name
    label_c = union_q.c.label
    pk_c = union_q.c.pk

    outer = select(
        ts_c, src_c, action_c, target_type_c, target_id_c, actor_c, group_c, label_c, pk_c
    )

    # Apply common filters
    if actor:
        outer = outer.where(actor_c == actor)
    if since:
        outer = outer.where(ts_c >= since)
    if until:
        outer = outer.where(ts_c <= until)

    # Group ACL
    if user.role != "admin":
        if not user.accessible_groups:
            return AuditResponse(events=[], next_cursor=None)
        # Drop non-host-scoped events (e.g. enrollment.token_issued) for
        # non-admins to prevent cross-tenant leaks. They survive only if
        # their group_name matches the caller's accessible groups.
        outer = outer.where(group_c.in_(user.accessible_groups))

    # Cursor: strictly past (ts DESC, src ASC, pk ASC).
    if cursor_ts is not None:
        outer = outer.where(
            or_(
                ts_c < cursor_ts,
                and_(ts_c == cursor_ts, src_c > cursor_src),
                and_(ts_c == cursor_ts, src_c == cursor_src, pk_c > cursor_pk),
            )
        )

    outer = outer.order_by(ts_c.desc(), src_c.asc(), pk_c.asc()).limit(limit + 1)

    rows = (await db.execute(outer)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    # For settings.* events the rich payload lives on ``audit_events.payload``
    # — fetch them in a single round-trip keyed by the source row's audit_id
    # (which equals ``pk`` for the settings sub-sources).
    settings_srcs = {
        "set_g_new", "set_g_del", "set_u_new", "set_u_upd", "set_u_del",
    }
    settings_pks = [r.pk for r in rows if r.src in settings_srcs]
    payloads_by_id: dict[str, dict[str, Any]] = {}
    if settings_pks:
        # ``pk`` is the cast(audit_events.id, String); compare via cast both
        # sides to stay dialect-agnostic (SQLite stores UUIDs as VARCHAR).
        payload_rows = (
            await db.execute(
                select(
                    cast(AuditEventRow.id, String).label("id"),
                    AuditEventRow.payload,
                ).where(cast(AuditEventRow.id, String).in_(settings_pks))
            )
        ).all()
        payloads_by_id = {row.id: (row.payload or {}) for row in payload_rows}

    events: list[AuditEvent] = []
    for r in rows:
        if r.src in settings_srcs:
            metadata: dict[str, Any] = dict(payloads_by_id.get(r.pk, {}))
        else:
            metadata = {"group_name": r.group_name} if r.group_name else {}

        events.append(
            AuditEvent(
                id=f"{r.src}:{r.pk}",
                ts=r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=timezone.utc),
                actor=r.actor or "system",
                action=r.action,  # type: ignore[arg-type]
                target_type=r.target_type,  # type: ignore[arg-type]
                target_id=r.target_id,
                target_label=r.label,
                metadata=metadata,
            )
        )

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last.ts, last.src, last.pk)

    return AuditResponse(events=events, next_cursor=next_cursor)


# Silence "imported but unused" for symbols kept here for readability in
# case we later need to grep for them.
_ = (column, literal_column)
