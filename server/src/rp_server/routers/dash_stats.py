"""Aggregated fleet statistics endpoint for the SvelteKit SPA (ADR-0009).

The other ``/v1/dash/*`` endpoints expose *current* state. This module
exposes *historical roll-ups* over a configurable range (24h / 7d / 30d /
90d): fleet uptime, command success rate, audit activity by actor/action,
per-host uptime calculated from heartbeat coverage.

All queries are scoped by the caller's ``accessible_groups`` — non-admin
viewers only see hosts (and the commands / audit events that reference
those hosts) inside their groups.

TimescaleDB notes
-----------------
The daily-bucket query uses ``time_bucket('1 day', issued_at)`` so the
hypertable's compressed chunks short-circuit cleanly. The function exists
in production (TimescaleDB extension) but not in SQLite, so the helper
detects the dialect and falls back to ``date(...)`` for tests.

Performance budget: < 500 ms for ``range=7d`` on an 8-host fleet (the
ADR-0009 production target). The heartbeat coverage query is the
expensive one — we bucket to 1-minute granularity and ``count(*)`` per
host in a single round-trip rather than running 8 separate per-host
queries.

Endpoint
--------
- ``GET /v1/dash/stats?range=24h|7d|30d|90d``
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func, or_, select, text

from rp_server.database import DbSession
from rp_server.deps import current_user
from rp_server.middleware.group_filter import filter_hosts_by_user_groups
from rp_server.models import AuditEvent, Command, Heartbeat, Host, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash", tags=["dash"])


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Status thresholds (mirrors dash_api). 60s online, 180s stale, beyond offline.
ONLINE_THRESHOLD_S = 60

# Expected heartbeat cadence: agents send roughly one heartbeat every 15s.
# Per-host uptime is computed as
#   (distinct 1-minute buckets with a heartbeat in the range) /
#   (total 1-minute buckets in the range).
# 1-minute buckets are forgiving enough that a single missed heartbeat
# doesn't ding the host's uptime score.
HEARTBEAT_BUCKET_S = 60

RANGE_DURATIONS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

RangeKey = Literal["24h", "7d", "30d", "90d"]


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class FleetStats(BaseModel):
    total_hosts: int
    online_now: int
    offline_now: int
    uptime_percent: float


class CommandTypeCount(BaseModel):
    type: str
    count: int


class CommandDailyBucket(BaseModel):
    day: str
    issued: int
    succeeded: int
    failed: int


class CommandsStats(BaseModel):
    total: int
    succeeded: int
    failed: int
    pending: int
    success_rate: float
    by_type: list[CommandTypeCount]
    daily: list[CommandDailyBucket]


class HeartbeatsStats(BaseModel):
    total: int
    per_host_avg_per_min: float
    stale_events: int
    offline_events: int


class HostUptime(BaseModel):
    hostname: str
    uptime_percent: float
    downtime_minutes: int


class AuditActionCount(BaseModel):
    action: str
    count: int


class AuditActorCount(BaseModel):
    actor: str
    count: int


class AuditSummary(BaseModel):
    total_events: int
    by_action: list[AuditActionCount]
    by_actor: list[AuditActorCount]


class StatsResponse(BaseModel):
    range: RangeKey
    fleet: FleetStats
    commands: CommandsStats
    heartbeats: HeartbeatsStats
    uptime_per_host: list[HostUptime]
    audit_summary: AuditSummary


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _is_postgres(db: Any) -> bool:
    """Detect whether the active session is talking to Postgres.

    We use ``time_bucket()`` on Postgres+TimescaleDB and degrade to
    ``date()`` on SQLite (test fixture).
    """
    try:
        return db.bind.dialect.name == "postgresql"
    except AttributeError:  # pragma: no cover — defensive
        return False


async def _accessible_host_ids(
    db: Any, user: User
) -> tuple[list[Any], list[str], dict[Any, str]]:
    """Resolve the set of host ids the user can see.

    Returns ``(host_ids, group_names, hostname_by_id)``. Admins get every
    host; non-admins are scoped by ``accessible_groups``.
    """
    stmt = select(Host.id, Host.hostname, Host.group_name)
    stmt = filter_hosts_by_user_groups(stmt, user)
    rows = (await db.execute(stmt)).all()
    host_ids = [r.id for r in rows]
    groups = sorted({r.group_name for r in rows if r.group_name})
    hostname_by_id = {r.id: r.hostname for r in rows}
    return host_ids, groups, hostname_by_id


# --------------------------------------------------------------------------- #
# /v1/dash/stats
# --------------------------------------------------------------------------- #


@router.get("/stats", response_model=StatsResponse)
async def stats(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    range_param: Annotated[
        str,
        Query(alias="range", description="24h | 7d | 30d | 90d"),
    ] = "7d",
) -> StatsResponse:
    """Aggregated operational statistics for the dashboard /stats page."""
    if range_param not in RANGE_DURATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid range '{range_param}'; must be one of {sorted(RANGE_DURATIONS)}",
        )
    window = RANGE_DURATIONS[range_param]
    now = datetime.now(timezone.utc)
    start = now - window
    range_seconds = window.total_seconds()
    range_minutes = max(1, int(range_seconds // 60))

    host_ids, _, hostname_by_id = await _accessible_host_ids(db, user)
    is_pg = _is_postgres(db)

    # ----- Fleet -----------------------------------------------------------
    total_hosts = len(host_ids)
    online_cutoff = now - timedelta(seconds=ONLINE_THRESHOLD_S)
    online_now = 0
    if host_ids:
        online_stmt = (
            select(func.count(Host.id))
            .where(Host.id.in_(host_ids))
            .where(Host.last_seen_at.is_not(None))
            .where(Host.last_seen_at >= online_cutoff)
        )
        online_now = int((await db.execute(online_stmt)).scalar() or 0)
    offline_now = max(0, total_hosts - online_now)

    # ----- Per-host uptime (and aggregate fleet uptime) --------------------
    # Count distinct 1-minute buckets per host that contain >= 1 heartbeat.
    # The result divided by the bucket-count over the whole range is the
    # uptime ratio. ``time_bucket`` on Postgres, ``strftime`` on SQLite.
    uptime_rows: list[HostUptime] = []
    fleet_uptime_pct = 0.0
    total_heartbeats = 0
    if host_ids:
        if is_pg:
            uptime_q = text(
                """
                SELECT host_id, COUNT(*) AS bucket_count, total.total_count
                FROM (
                    SELECT
                        host_id,
                        time_bucket(:bucket_interval, ts) AS bucket
                    FROM heartbeats
                    WHERE host_id = ANY(:host_ids)
                      AND ts >= :start_time
                    GROUP BY host_id, bucket
                ) bucketed
                CROSS JOIN (
                    SELECT COUNT(*)::bigint AS total_count
                    FROM heartbeats
                    WHERE host_id = ANY(:host_ids)
                      AND ts >= :start_time
                ) total
                GROUP BY host_id, total.total_count
                """
            )
            result = await db.execute(
                uptime_q,
                {
                    "bucket_interval": timedelta(seconds=HEARTBEAT_BUCKET_S),
                    "host_ids": host_ids,
                    "start_time": start,
                },
            )
            buckets_by_host: dict[Any, int] = {}
            for row in result.fetchall():
                buckets_by_host[row.host_id] = int(row.bucket_count)
                total_heartbeats = int(row.total_count)
        else:
            # SQLite fallback: bucket by integer-floored minute. The raw
            # ``text()`` query returns ``host_id`` as a TEXT scalar (SQLite
            # has no UUID type), so we normalise to ``str`` on both sides
            # of the lookup.
            uptime_q = text(
                """
                SELECT host_id, COUNT(DISTINCT bucket) AS bucket_count
                FROM (
                    SELECT host_id,
                           CAST(strftime('%s', ts) AS INTEGER) / :bucket_s AS bucket
                    FROM heartbeats
                    WHERE ts >= :start_time
                )
                GROUP BY host_id
                """
            )
            result = await db.execute(
                uptime_q,
                {"bucket_s": HEARTBEAT_BUCKET_S, "start_time": start},
            )
            raw_buckets = {
                str(row.host_id): int(row.bucket_count) for row in result.fetchall()
            }
            accessible_str_ids = {str(hid) for hid in host_ids}
            buckets_by_host = {
                hid: count for hid, count in raw_buckets.items() if hid in accessible_str_ids
            }
            total_q = select(func.count()).select_from(Heartbeat).where(
                Heartbeat.host_id.in_(host_ids),
                Heartbeat.ts >= start,
            )
            total_heartbeats = int((await db.execute(total_q)).scalar() or 0)

        host_uptime_sum = 0.0
        for hid in host_ids:
            # Lookup table is keyed by str on SQLite, by UUID on Postgres.
            # Try both so callers don't have to care about the dialect.
            bucket_count = buckets_by_host.get(hid)
            if bucket_count is None:
                bucket_count = buckets_by_host.get(str(hid), 0)
            ratio = min(1.0, bucket_count / range_minutes) if range_minutes else 0.0
            pct = round(ratio * 100, 2)
            downtime_min = max(0, range_minutes - bucket_count)
            uptime_rows.append(
                HostUptime(
                    hostname=hostname_by_id[hid],
                    uptime_percent=pct,
                    downtime_minutes=downtime_min,
                )
            )
            host_uptime_sum += pct
        uptime_rows.sort(key=lambda h: h.hostname)
        fleet_uptime_pct = round(host_uptime_sum / total_hosts, 2) if total_hosts else 0.0

    # ----- Commands --------------------------------------------------------
    cmd_total = cmd_succeeded = cmd_failed = cmd_pending = 0
    by_type: list[CommandTypeCount] = []
    daily: list[CommandDailyBucket] = []
    if host_ids:
        succeeded_expr = case((Command.exit_code == 0, 1), else_=0)
        failed_expr = case(
            (Command.exit_code.is_not(None), case((Command.exit_code != 0, 1), else_=0)),
            else_=0,
        )
        pending_expr = case(
            (Command.completed_at.is_(None), 1),
            else_=0,
        )
        agg_stmt = (
            select(
                func.count(Command.id).label("total"),
                func.sum(succeeded_expr).label("succeeded"),
                func.sum(failed_expr).label("failed"),
                func.sum(pending_expr).label("pending"),
            )
            .where(Command.host_id.in_(host_ids))
            .where(Command.issued_at >= start)
        )
        agg = (await db.execute(agg_stmt)).one()
        cmd_total = int(agg.total or 0)
        cmd_succeeded = int(agg.succeeded or 0)
        cmd_failed = int(agg.failed or 0)
        cmd_pending = int(agg.pending or 0)

        by_type_stmt = (
            select(Command.command_type, func.count(Command.id).label("count"))
            .where(Command.host_id.in_(host_ids))
            .where(Command.issued_at >= start)
            .group_by(Command.command_type)
            .order_by(func.count(Command.id).desc())
        )
        by_type_rows = (await db.execute(by_type_stmt)).all()
        by_type = [CommandTypeCount(type=r.command_type, count=int(r.count)) for r in by_type_rows]

        if is_pg:
            daily_q = text(
                """
                SELECT
                    time_bucket('1 day', issued_at) AS day,
                    COUNT(*) AS issued,
                    COUNT(*) FILTER (WHERE exit_code = 0) AS succeeded,
                    COUNT(*) FILTER (WHERE exit_code IS NOT NULL AND exit_code <> 0) AS failed
                FROM commands
                WHERE host_id = ANY(:host_ids)
                  AND issued_at >= :start_time
                GROUP BY day
                ORDER BY day ASC
                """
            )
            daily_rows = (
                await db.execute(daily_q, {"host_ids": host_ids, "start_time": start})
            ).fetchall()
            daily = [
                CommandDailyBucket(
                    day=row.day.date().isoformat()
                    if hasattr(row.day, "date")
                    else str(row.day)[:10],
                    issued=int(row.issued),
                    succeeded=int(row.succeeded),
                    failed=int(row.failed),
                )
                for row in daily_rows
            ]
        else:
            # SQLite: date() yields YYYY-MM-DD already.
            daily_q = text(
                """
                SELECT
                    date(issued_at) AS day,
                    COUNT(*) AS issued,
                    SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END) AS succeeded,
                    SUM(CASE WHEN exit_code IS NOT NULL AND exit_code <> 0 THEN 1 ELSE 0 END) AS failed
                FROM commands
                WHERE issued_at >= :start_time
                GROUP BY day
                ORDER BY day ASC
                """
            )
            daily_rows = (await db.execute(daily_q, {"start_time": start})).fetchall()
            daily = [
                CommandDailyBucket(
                    day=str(row.day),
                    issued=int(row.issued),
                    succeeded=int(row.succeeded or 0),
                    failed=int(row.failed or 0),
                )
                for row in daily_rows
            ]

    success_rate = round(cmd_succeeded / cmd_total, 3) if cmd_total else 0.0

    # ----- Heartbeats summary ---------------------------------------------
    per_host_avg = 0.0
    if total_hosts and total_heartbeats:
        per_host_avg = round(total_heartbeats / total_hosts / range_minutes, 3)

    # Stale/offline events: we don't have a dedicated table for transitions,
    # so we estimate from the host count whose last_seen falls outside the
    # online window but inside the range. Cheap and useful enough for a
    # summary card; the per-host timeline lives elsewhere.
    stale_events = 0
    offline_events = 0
    if host_ids:
        stale_cutoff = now - timedelta(seconds=180)
        stale_stmt = (
            select(func.count(Host.id))
            .where(Host.id.in_(host_ids))
            .where(Host.last_seen_at.is_not(None))
            .where(Host.last_seen_at < online_cutoff)
            .where(Host.last_seen_at >= stale_cutoff)
        )
        offline_stmt = (
            select(func.count(Host.id))
            .where(Host.id.in_(host_ids))
            .where(Host.last_seen_at.is_(None) | (Host.last_seen_at < stale_cutoff))
        )
        stale_events = int((await db.execute(stale_stmt)).scalar() or 0)
        offline_events = int((await db.execute(offline_stmt)).scalar() or 0)

    # ----- Audit summary --------------------------------------------------
    # Audit events are scoped by admin / non-admin: non-admins only see
    # events whose payload group_name is in their accessible_groups, mirror-
    # ing the audit timeline router. We compute it cheaply: admins get all,
    # non-admins get the subset with a matching ``payload->>'group_name'``.
    audit_filter_stmts = [AuditEvent.ts >= start]
    if user.role != "admin":
        if not user.accessible_groups:
            audit_filter_stmts.append(func.lower(AuditEvent.action) == "__never__")
        elif is_pg:
            # Postgres JSONB path access for the group key. We pass the
            # accessible group list as an ARRAY literal via ``= ANY(...)``.
            from sqlalchemy import bindparam
            from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

            audit_filter_stmts.append(
                text("(payload->>'group_name') = ANY(:audit_groups)").bindparams(
                    bindparam(
                        "audit_groups",
                        list(user.accessible_groups),
                        type_=PG_ARRAY(String),
                    )
                )
            )
        else:
            # SQLite: payload is stringified JSON; just match the substring.
            # This is a best-effort coarse filter for the test path.
            substrings = [
                cast(AuditEvent.payload, String).like(f'%"group_name": "{g}"%')
                for g in user.accessible_groups
            ]
            if substrings:
                audit_filter_stmts.append(or_(*substrings))

    total_events_stmt = select(func.count(AuditEvent.id)).where(*audit_filter_stmts)
    total_audit_events = int((await db.execute(total_events_stmt)).scalar() or 0)

    by_action_stmt = (
        select(AuditEvent.action, func.count(AuditEvent.id).label("count"))
        .where(*audit_filter_stmts)
        .group_by(AuditEvent.action)
        .order_by(func.count(AuditEvent.id).desc())
        .limit(10)
    )
    by_action_rows = (await db.execute(by_action_stmt)).all()
    by_action = [AuditActionCount(action=r.action, count=int(r.count)) for r in by_action_rows]

    by_actor_stmt = (
        select(AuditEvent.actor, func.count(AuditEvent.id).label("count"))
        .where(*audit_filter_stmts)
        .group_by(AuditEvent.actor)
        .order_by(func.count(AuditEvent.id).desc())
        .limit(5)
    )
    by_actor_rows = (await db.execute(by_actor_stmt)).all()
    by_actor = [AuditActorCount(actor=r.actor, count=int(r.count)) for r in by_actor_rows]

    logger.debug(
        "dash stats computed",
        extra={
            "user_id": str(user.id),
            "range": range_param,
            "total_hosts": total_hosts,
            "total_commands": cmd_total,
            "total_audit_events": total_audit_events,
        },
    )

    return StatsResponse(
        range=range_param,  # type: ignore[arg-type]
        fleet=FleetStats(
            total_hosts=total_hosts,
            online_now=online_now,
            offline_now=offline_now,
            uptime_percent=fleet_uptime_pct,
        ),
        commands=CommandsStats(
            total=cmd_total,
            succeeded=cmd_succeeded,
            failed=cmd_failed,
            pending=cmd_pending,
            success_rate=success_rate,
            by_type=by_type,
            daily=daily,
        ),
        heartbeats=HeartbeatsStats(
            total=total_heartbeats,
            per_host_avg_per_min=per_host_avg,
            stale_events=stale_events,
            offline_events=offline_events,
        ),
        uptime_per_host=uptime_rows,
        audit_summary=AuditSummary(
            total_events=total_audit_events,
            by_action=by_action,
            by_actor=by_actor,
        ),
    )
