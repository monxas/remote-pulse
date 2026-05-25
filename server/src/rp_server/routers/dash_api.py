"""JSON API for the SvelteKit dashboard SPA (ADR-0009 Phase 1).

All endpoints live under ``/v1/dash/*`` and require an authenticated user
(``current_user`` dependency). Host queries are scoped by
``filter_hosts_by_user_groups`` so non-admin viewers only see their groups.

Endpoints
---------
- ``GET /v1/dash/me`` — shell user info
- ``GET /v1/dash/overview`` — fleet roll-up for the stat cards
- ``GET /v1/dash/hosts`` — enriched host list with sparkline buffer
- ``GET /v1/dash/hosts/{host_id}/timeseries`` — full-resolution charts
- ``GET /v1/dash/stream`` — Server-Sent Events firehose

See ADR-0009 §"Phase 1 — JSON API" for the full contract.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sse_starlette.sse import EventSourceResponse

from rp_server.database import DbSession
from rp_server.deps import current_user
from rp_server.events import event_bus
from rp_server.middleware.group_filter import filter_hosts_by_user_groups
from rp_server.models import Command, Heartbeat, Host, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash", tags=["dash"])


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Status thresholds (seconds). Heartbeat is expected every ~15s, so 60s is
# "fresh", 180s is "stale, still probably alive", beyond that is offline.
ONLINE_THRESHOLD_S = 60
STALE_THRESHOLD_S = 180

# Sparkline window options exposed in the host-list endpoint. Cap at 15m to
# keep payload size bounded (60 buckets * N hosts * 2 series).
SPARKLINE_WINDOWS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}
SPARKLINE_BUCKETS = 60  # Always 60 points per sparkline for stable rendering

# Timeseries window → bucket sizing (seconds). Targets ~60-360 points/series.
TIMESERIES_BUCKETS: dict[str, tuple[int, int]] = {
    # window_str: (window_s, bucket_s)
    "5m": (300, 5),
    "15m": (900, 15),
    "1h": (3600, 60),
    "6h": (21600, 300),
    "24h": (86400, 900),
    "7d": (604800, 3600),
}

# Allowed metric names for the timeseries endpoint. Whitelist defends against
# SQL injection — the metric name is interpolated into the GROUP BY clause.
ALLOWED_METRICS: frozenset[str] = frozenset(
    {"cpu_pct", "mem_pct", "load_1m", "uptime_s", "net_rx_kbps", "net_tx_kbps"}
)
# Metrics that physically exist in the ``heartbeats`` table. ``net_*`` lives
# in ``metric_samples`` (custom metrics); querying it from heartbeats yields
# all-nulls. We still accept the parameter so the contract is stable, but
# we return empty arrays for now (Phase 2 will fetch from metric_samples).
HEARTBEAT_METRICS: frozenset[str] = frozenset(
    {"cpu_pct", "mem_pct", "load_1m", "uptime_s"}
)


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class MeResponse(BaseModel):
    """Shell user info returned by ``GET /v1/dash/me``."""

    user_id: uuid.UUID
    email: str
    name: str | None
    role: str
    accessible_groups: list[str]


class OverviewResponse(BaseModel):
    """Fleet roll-up returned by ``GET /v1/dash/overview``."""

    total: int
    online: int
    stale: int
    offline: int
    pending_approvals: int
    online_pct: float
    online_pct_24h_ago: float | None


class CurrentMetrics(BaseModel):
    """Most-recent metric values for a host."""

    cpu_pct: float | None = None
    mem_pct: float | None = None
    load_1m: float | None = None
    uptime_s: int | None = None


class SparklineBuffer(BaseModel):
    """Bucketed sparkline buffer embedded in host-list entries."""

    window_s: int
    bucket_s: int
    ts: list[int]
    cpu_pct: list[float | None]
    mem_pct: list[float | None]


class HostEntry(BaseModel):
    """Enriched host row for the overview table."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    group_name: str | None
    status: Literal["online", "stale", "offline"]
    last_seen_at: datetime | None
    last_seen_seconds_ago: int | None
    os_family: str
    agent_version: str
    tailscale_ip: str | None
    current: CurrentMetrics
    sparkline: SparklineBuffer


class HostsResponse(BaseModel):
    """Envelope returned by ``GET /v1/dash/hosts``."""

    hosts: list[HostEntry]
    groups: list[str]


class TimeseriesResponse(BaseModel):
    """Payload returned by ``GET /v1/dash/hosts/{host_id}/timeseries``.

    The field set is dynamic (only requested series appear), so the model
    uses ``extra='allow'`` and we build the dict by hand.
    """

    model_config = ConfigDict(extra="allow")

    host_id: uuid.UUID
    window_s: int
    bucket_s: int
    ts: list[int]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _classify_status(
    last_seen_at: datetime | None, now: datetime
) -> Literal["online", "stale", "offline"]:
    """Map ``last_seen_at`` to a status label.

    online: <= 60s, stale: <= 180s, offline: older or never seen.
    """
    if last_seen_at is None:
        return "offline"
    # Both timestamps are tz-aware in the codebase, but defensive normalisation
    # keeps us robust to a future SQLite-backed test that drops tzinfo.
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    age_s = (now - last_seen_at).total_seconds()
    if age_s <= ONLINE_THRESHOLD_S:
        return "online"
    if age_s <= STALE_THRESHOLD_S:
        return "stale"
    return "offline"


def _seconds_ago(last_seen_at: datetime | None, now: datetime) -> int | None:
    """Seconds since last_seen_at, or None if never seen."""
    if last_seen_at is None:
        return None
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    return max(0, int((now - last_seen_at).total_seconds()))


async def _user_accessible_groups(db: DbSession, user: User) -> list[str]:
    """Resolve the group list a user can see.

    Admin → all distinct group_names in the DB. Viewer/operator → the
    ``accessible_groups`` array on the user row.
    """
    if user.role == "admin":
        stmt = select(Host.group_name).where(Host.group_name.isnot(None)).distinct()
        result = await db.execute(stmt)
        return sorted({g for g in result.scalars().all() if g})
    return list(user.accessible_groups or [])


# --------------------------------------------------------------------------- #
# /v1/dash/me
# --------------------------------------------------------------------------- #


@router.get("/me", response_model=MeResponse)
async def me(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> MeResponse:
    """Return the authenticated user info for the SPA shell."""
    accessible = await _user_accessible_groups(db, user)
    return MeResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        accessible_groups=accessible,
    )


# --------------------------------------------------------------------------- #
# /v1/dash/overview
# --------------------------------------------------------------------------- #


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> OverviewResponse:
    """Fleet roll-up: counts per status + pending approvals + 24h delta."""
    now = datetime.now(timezone.utc)
    online_cutoff = now - timedelta(seconds=ONLINE_THRESHOLD_S)
    stale_cutoff = now - timedelta(seconds=STALE_THRESHOLD_S)

    # Compute status counts in a single round-trip via filtered aggregates.
    # ``count(*) FILTER (WHERE ...)`` is supported by Postgres natively and
    # emulated by SQLA for other dialects; offline is derived (total - rest)
    # to keep the SQL readable.
    stmt = (
        select(
            func.count(Host.id).label("total"),
            func.count(Host.id)
            .filter(Host.last_seen_at.is_not(None), Host.last_seen_at >= online_cutoff)
            .label("online"),
            func.count(Host.id)
            .filter(
                Host.last_seen_at.is_not(None),
                Host.last_seen_at < online_cutoff,
                Host.last_seen_at >= stale_cutoff,
            )
            .label("stale"),
        )
        .select_from(Host)
    )
    stmt = filter_hosts_by_user_groups(stmt, user)
    row = (await db.execute(stmt)).one()
    total = int(row.total or 0)
    online_count = int(row.online or 0)
    stale_count = int(row.stale or 0)
    offline_count = max(0, total - online_count - stale_count)

    online_pct = round((online_count / total) * 100, 1) if total else 0.0

    # 24h delta: snapshot how many hosts had a heartbeat in the 60s window
    # ending 24h ago. Approximate "was online" by checking for any heartbeat
    # in [-24h-60s, -24h].
    ago_24h = now - timedelta(hours=24)
    ago_24h_minus = ago_24h - timedelta(seconds=ONLINE_THRESHOLD_S)

    hosts_subq = filter_hosts_by_user_groups(select(Host.id), user).subquery()
    snapshot_stmt = (
        select(func.count(func.distinct(Heartbeat.host_id)))
        .where(
            Heartbeat.host_id.in_(select(hosts_subq.c.id)),
            Heartbeat.ts >= ago_24h_minus,
            Heartbeat.ts <= ago_24h,
        )
    )
    snapshot_count = (await db.execute(snapshot_stmt)).scalar()
    online_pct_24h_ago: float | None
    if total > 0 and snapshot_count is not None and snapshot_count > 0:
        online_pct_24h_ago = round((int(snapshot_count) / total) * 100, 1)
    else:
        online_pct_24h_ago = None

    # Pending approvals scoped to hosts the user can see.
    pending_stmt = (
        select(func.count(Command.id))
        .where(
            Command.approval_token.is_not(None),
            Command.human_approved.is_(False),
            Command.rejected_reason.is_(None),
            Command.host_id.in_(select(hosts_subq.c.id)),
        )
    )
    pending = int((await db.execute(pending_stmt)).scalar() or 0)

    logger.debug(
        "dash overview computed",
        extra={
            "user_id": str(user.id),
            "total": total,
            "online": online_count,
            "stale": stale_count,
            "offline": offline_count,
            "pending_approvals": pending,
        },
    )

    return OverviewResponse(
        total=total,
        online=online_count,
        stale=stale_count,
        offline=offline_count,
        pending_approvals=pending,
        online_pct=online_pct,
        online_pct_24h_ago=online_pct_24h_ago,
    )


# --------------------------------------------------------------------------- #
# /v1/dash/hosts
# --------------------------------------------------------------------------- #


async def _fetch_sparkline_buffer(
    db: DbSession,
    host_ids: list[uuid.UUID],
    window_s: int,
    bucket_s: int,
    now: datetime,
) -> dict[uuid.UUID, dict[str, list[Any]]]:
    """Fetch bucketed cpu/mem series for many hosts in a single query.

    Returns ``{host_id: {"ts": [...], "cpu_pct": [...], "mem_pct": [...]}}``.
    Uses TimescaleDB's ``time_bucket`` for stable bucket alignment.
    """
    if not host_ids:
        return {}
    start_time = now - timedelta(seconds=window_s)

    # One query, group by (host_id, bucket). Backend collates in Python.
    query = text(
        """
        SELECT
            host_id,
            time_bucket(:bucket_interval, ts) AS bucket,
            avg(cpu_pct) AS cpu_avg,
            avg(mem_pct) AS mem_avg
        FROM heartbeats
        WHERE host_id = ANY(:host_ids)
          AND ts >= :start_time
        GROUP BY host_id, bucket
        ORDER BY host_id, bucket ASC
        """
    )
    result = await db.execute(
        query,
        {
            "bucket_interval": timedelta(seconds=bucket_s),
            "host_ids": host_ids,
            "start_time": start_time,
        },
    )

    by_host: dict[uuid.UUID, dict[str, list[Any]]] = {}
    for row in result.fetchall():
        hid = row.host_id
        bucket = by_host.setdefault(hid, {"ts": [], "cpu_pct": [], "mem_pct": []})
        bucket["ts"].append(int(row.bucket.timestamp()))
        bucket["cpu_pct"].append(float(row.cpu_avg) if row.cpu_avg is not None else None)
        bucket["mem_pct"].append(float(row.mem_avg) if row.mem_avg is not None else None)
    return by_host


async def _fetch_current_metrics(
    db: DbSession,
    host_ids: list[uuid.UUID],
) -> dict[uuid.UUID, CurrentMetrics]:
    """Most recent heartbeat per host — single LATERAL/DISTINCT ON query.

    Avoids N+1 by using PG's ``DISTINCT ON (host_id)`` ordering trick.
    """
    if not host_ids:
        return {}
    query = text(
        """
        SELECT DISTINCT ON (host_id)
            host_id, ts, cpu_pct, mem_pct, load_1m, uptime_s
        FROM heartbeats
        WHERE host_id = ANY(:host_ids)
        ORDER BY host_id, ts DESC
        """
    )
    result = await db.execute(query, {"host_ids": host_ids})
    out: dict[uuid.UUID, CurrentMetrics] = {}
    for row in result.fetchall():
        out[row.host_id] = CurrentMetrics(
            cpu_pct=float(row.cpu_pct) if row.cpu_pct is not None else None,
            mem_pct=float(row.mem_pct) if row.mem_pct is not None else None,
            load_1m=float(row.load_1m) if row.load_1m is not None else None,
            uptime_s=int(row.uptime_s) if row.uptime_s is not None else None,
        )
    return out


def _tailscale_ip_from_host(host: Host) -> str | None:
    """Pull tailscale_ip from host.extra metadata if present.

    The agent reports its tailnet IP in the ``metadata`` JSONB column.
    """
    extra = host.extra or {}
    ip = extra.get("tailscale_ip") or extra.get("ts_ip")
    return str(ip) if ip else None


@router.get("/hosts", response_model=HostsResponse)
async def list_hosts_enriched(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    group: str | None = Query(default=None, description="Filter by group ('all' = no filter)"),
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="online | stale | offline | all"),
    ] = None,
    q: str | None = Query(default=None, description="Case-insensitive hostname substring"),
    window: str = Query(default="5m", description="Sparkline window: 1m | 5m | 15m"),
) -> HostsResponse:
    """Enriched host list for the dashboard overview table."""
    if window not in SPARKLINE_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid window '{window}'; must be one of {sorted(SPARKLINE_WINDOWS)}",
        )
    window_s = SPARKLINE_WINDOWS[window]
    bucket_s = max(window_s // SPARKLINE_BUCKETS, 1)
    now = datetime.now(timezone.utc)

    # Base host query, scoped by ACL
    stmt = select(Host).order_by(Host.hostname)
    stmt = filter_hosts_by_user_groups(stmt, user)
    if group and group != "all":
        stmt = stmt.where(Host.group_name == group)
    if q:
        # Postgres ilike for case-insensitive substring; works on SQLite too
        stmt = stmt.where(Host.hostname.ilike(f"%{q}%"))
    hosts = (await db.execute(stmt)).scalars().all()

    # Pre-compute status server-side so we can post-filter by status param.
    rows: list[tuple[Host, Literal["online", "stale", "offline"]]] = [
        (h, _classify_status(h.last_seen_at, now)) for h in hosts
    ]
    if status_filter and status_filter != "all":
        if status_filter not in {"online", "stale", "offline"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{status_filter}'",
            )
        rows = [(h, s) for h, s in rows if s == status_filter]

    host_ids = [h.id for h, _ in rows]
    current_by_host = await _fetch_current_metrics(db, host_ids)
    spark_by_host = await _fetch_sparkline_buffer(db, host_ids, window_s, bucket_s, now)

    entries: list[HostEntry] = []
    for host, host_status in rows:
        spark_data = spark_by_host.get(
            host.id, {"ts": [], "cpu_pct": [], "mem_pct": []}
        )
        entries.append(
            HostEntry(
                id=host.id,
                hostname=host.hostname,
                group_name=host.group_name,
                status=host_status,
                last_seen_at=host.last_seen_at,
                last_seen_seconds_ago=_seconds_ago(host.last_seen_at, now),
                os_family=host.os,
                agent_version=host.agent_version,
                tailscale_ip=_tailscale_ip_from_host(host),
                current=current_by_host.get(host.id, CurrentMetrics()),
                sparkline=SparklineBuffer(
                    window_s=window_s,
                    bucket_s=bucket_s,
                    ts=spark_data["ts"],
                    cpu_pct=spark_data["cpu_pct"],
                    mem_pct=spark_data["mem_pct"],
                ),
            )
        )

    groups = await _user_accessible_groups(db, user)

    return HostsResponse(hosts=entries, groups=groups)


# --------------------------------------------------------------------------- #
# /v1/dash/hosts/{host_id}/timeseries
# --------------------------------------------------------------------------- #


@router.get("/hosts/{host_id}/timeseries")
async def host_timeseries(
    host_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    window: str = Query(default="1h", description="5m | 15m | 1h | 6h | 24h | 7d"),
    series: str = Query(
        default="cpu_pct,mem_pct,load_1m",
        description="Comma-separated metric names",
    ),
) -> dict[str, Any]:
    """Full-resolution time-series for the host-detail charts."""
    if window not in TIMESERIES_BUCKETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid window '{window}'; must be one of {sorted(TIMESERIES_BUCKETS)}",
        )
    window_s, bucket_s = TIMESERIES_BUCKETS[window]

    # Parse + whitelist series. SQL-injection defense: only metrics in
    # ALLOWED_METRICS get past the gate, and we also verify the name is
    # identifier-safe before string-interpolating into the SELECT.
    requested = [s.strip() for s in series.split(",") if s.strip()]
    safe_metrics: list[str] = []
    for m in requested:
        if m not in ALLOWED_METRICS:
            continue
        if not m.replace("_", "").isalnum():
            continue
        safe_metrics.append(m)

    if not safe_metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No valid metrics requested; allowed: {sorted(ALLOWED_METRICS)}",
        )

    # ACL check: caller must be able to see the host.
    stmt = select(Host).where(Host.id == host_id)
    stmt = filter_hosts_by_user_groups(stmt, user)
    host = (await db.execute(stmt)).scalar_one_or_none()
    if not host:
        # Match the existing /dash/host/:id/sparkline-data behaviour: collapse
        # to 404 so we don't leak existence of hosts in other groups.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found or access denied",
        )

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(seconds=window_s)

    # Heartbeat-resident metrics get bucketed in one query each. We could
    # union them but Postgres handles the parallel queries quickly with the
    # (host_id, ts) hypertable index, and the code stays readable.
    series_data: dict[str, list[float | None]] = {m: [] for m in safe_metrics}
    timestamps: list[int] = []

    heartbeat_metrics = [m for m in safe_metrics if m in HEARTBEAT_METRICS]
    other_metrics = [m for m in safe_metrics if m not in HEARTBEAT_METRICS]

    if heartbeat_metrics:
        # Build a single SELECT that buckets all requested heartbeat metrics
        # at once. metric names are pre-validated against ALLOWED_METRICS.
        select_parts = ", ".join(f"avg({m}) AS {m}" for m in heartbeat_metrics)
        query = text(
            f"""
            SELECT
                time_bucket(:bucket_interval, ts) AS bucket,
                {select_parts}
            FROM heartbeats
            WHERE host_id = :host_id
              AND ts >= :start_time
            GROUP BY bucket
            ORDER BY bucket ASC
            """  # noqa: S608 — metrics whitelisted above
        )
        result = await db.execute(
            query,
            {
                "bucket_interval": timedelta(seconds=bucket_s),
                "host_id": host_id,
                "start_time": start_time,
            },
        )
        for row in result.fetchall():
            timestamps.append(int(row.bucket.timestamp()))
            for m in heartbeat_metrics:
                v = getattr(row, m)
                series_data[m].append(float(v) if v is not None else None)

    # Non-heartbeat metrics (net_*) — TODO Phase 2: fetch from metric_samples.
    # For now, fill with nulls aligned to the heartbeat timestamps.
    for m in other_metrics:
        series_data[m] = [None] * len(timestamps)

    payload: dict[str, Any] = {
        "host_id": str(host_id),
        "window_s": window_s,
        "bucket_s": bucket_s,
        "ts": timestamps,
    }
    payload.update(series_data)
    return payload


# --------------------------------------------------------------------------- #
# /v1/dash/stream — Server-Sent Events
# --------------------------------------------------------------------------- #


def _event_visible_to_user(user: User, payload: dict[str, Any]) -> bool:
    """Best-effort group ACL filter for SSE events.

    Admins see everything. Non-admins see events whose payload either:
    - Has no ``group_name`` field (treated as global, e.g. approval.created
      where we don't know the host group cheaply), OR
    - Has a ``group_name`` in their ``accessible_groups``.

    Publishers SHOULD include ``group_name`` in event payloads so non-admin
    viewers don't leak cross-tenant updates. The heartbeat publisher does
    this; approvals fall back to "global" until Phase 2 adds enrichment.
    """
    if user.role == "admin":
        return True
    group = payload.get("group_name")
    if group is None:
        # Conservative: drop non-tagged events to prevent leaks.
        return False
    return group in (user.accessible_groups or [])


@router.get("/stream")
async def stream(
    request: Request,
    user: Annotated[User, Depends(current_user)],
) -> EventSourceResponse:
    """Server-Sent Events firehose for live dashboard updates.

    Events
    ------
    - ``host.heartbeat`` — every heartbeat ingest
    - ``host.status_change`` — online ↔ stale ↔ offline transitions
    - ``command.status_change`` — command lifecycle (terminal states)
    - ``approval.created`` — new Telegram approval request

    The endpoint stays open until the client disconnects. Sends ``:keepalive``
    comments every 20s via ``ping=20`` so reverse proxies don't buffer.

    Phase 1 fan-out is per-process (see ``rp_server.events`` docstring).
    """

    async def event_generator() -> Any:
        async for event_type, payload in event_bus.subscribe():
            # Client gone? Stop early so we release the queue slot.
            if await request.is_disconnected():
                break
            if not _event_visible_to_user(user, payload):
                continue
            yield {
                "event": event_type,
                "data": json.dumps(payload, default=str),
            }

    return EventSourceResponse(event_generator(), ping=20)


# Event publishes from other routers go through ``rp_server.events.fire_and_forget``
# directly (see heartbeat.py, approvals.py). Keeping the publish API there
# avoids circular imports between routers.
