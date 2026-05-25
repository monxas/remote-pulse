"""Web dashboard router for HTMX-driven UI.

F5 implementation. Server-side rendered dashboard with uPlot sparklines
and HTMX partial updates for live host monitoring.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text

from rp_server.database import DbSession
from rp_server.deps import current_user, current_user_optional
from rp_server.middleware.group_filter import filter_hosts_by_user_groups
from rp_server.models import Host, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dash", tags=["web"])

# Jinja2 templates setup
templates = Jinja2Templates(directory="src/rp_server/templates")

# Add custom filters and globals
templates.env.globals["now"] = datetime.now


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: DbSession,
    user: Annotated[User | None, Depends(current_user_optional)] = None,
    group_filter: str = Query(default="all", description="Filter by group name"),
):
    """Main dashboard page with host list and sparklines.

    HTMX-driven with auto-refresh every 5s on host rows.

    If the caller has no resolved identity (no session, no Tailscale-identity
    fallback), redirect to the OIDC login endpoint instead of returning 401 —
    browsers can follow it, curl users will see the 302.
    """
    if user is None:
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse(
            url=f"/auth/login?next={target}",
            status_code=302,
        )
    # Build query with user group filtering
    stmt = select(Host).order_by(Host.hostname)
    stmt = filter_hosts_by_user_groups(stmt, user)

    # Apply additional group filter if specified
    if group_filter != "all":
        stmt = stmt.where(Host.group_name == group_filter)

    result = await db.execute(stmt)
    hosts = result.scalars().all()

    # Get unique groups for filter dropdown (respecting user access)
    groups_stmt = select(Host.group_name).distinct()
    groups_stmt = filter_hosts_by_user_groups(groups_stmt, user)
    groups_result = await db.execute(groups_stmt)
    available_groups = sorted([g for g in groups_result.scalars().all() if g])

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "hosts": hosts,
            "available_groups": available_groups,
            "selected_group": group_filter,
        },
    )


@router.get("/hosts/refresh", response_class=HTMLResponse)
async def hosts_refresh_partial(
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    group_filter: str = Query(default="all"),
):
    """HTMX partial: refresh host rows.

    Polled every 5s via hx-trigger='every 5s' on tbody.
    """
    stmt = select(Host).order_by(Host.hostname)
    stmt = filter_hosts_by_user_groups(stmt, user)

    if group_filter != "all":
        stmt = stmt.where(Host.group_name == group_filter)

    result = await db.execute(stmt)
    hosts = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "partials/hosts_table_body.html",
        {
            "hosts": hosts,
        },
    )


@router.get("/host/{host_id}", response_class=HTMLResponse)
async def host_detail_partial(
    request: Request,
    host_id: UUID,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
):
    """HTMX partial: host detail card with expanded info."""
    stmt = select(Host).where(Host.id == host_id)
    stmt = filter_hosts_by_user_groups(stmt, user)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found or access denied",
        )

    # Get recent heartbeats for display
    heartbeats_query = text(
        """
        SELECT ts, cpu_pct, mem_pct, load_1m, uptime_s
        FROM heartbeats
        WHERE host_id = :host_id
        ORDER BY ts DESC
        LIMIT 10
        """
    )
    heartbeats_result = await db.execute(heartbeats_query, {"host_id": host_id})
    recent_heartbeats = heartbeats_result.fetchall()

    return templates.TemplateResponse(
        request,
        "partials/host_detail_card.html",
        {
            "host": host,
            "recent_heartbeats": recent_heartbeats,
        },
    )


@router.get("/host/{host_id}/sparkline-data")
async def sparkline_data_json(
    host_id: UUID,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    series: list[str] = Query(default=["cpu_pct", "mem_pct"]),
    window: str = Query(default="5m"),
):
    """JSON endpoint for uPlot sparkline data.

    Called by client-side uPlot.js to render sparklines.
    Returns time series in uPlot format: [[timestamps], [values1], [values2], ...]
    """
    # Verify user has access to this host
    stmt = select(Host).where(Host.id == host_id)
    stmt = filter_hosts_by_user_groups(stmt, user)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found or access denied",
        )

    # Parse window to seconds
    window_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
    }
    window_seconds = window_map.get(window, 300)
    bucket_seconds = max(window_seconds // 60, 1)

    start_time = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    # Build uPlot data structure
    uplot_data = []
    timestamps = []

    ALLOWED_METRICS = {"cpu_pct", "mem_pct", "load_1m", "uptime_s"}
    for metric in series:
        if metric not in ALLOWED_METRICS:
            continue
        # Defense-in-depth: even though `metric` is whitelisted, enforce
        # identifier-safe charset before SQL interpolation.
        if not metric.replace("_", "").isalnum():
            continue

        query = text(
            f"""
            SELECT
                time_bucket(:bucket_interval, ts) AS bucket,
                avg({metric}) AS avg_value
            FROM heartbeats
            WHERE host_id = :host_id
                AND ts >= :start_time
                AND {metric} IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )

        result = await db.execute(
            query,
            {
                "bucket_interval": timedelta(seconds=bucket_seconds),
                "host_id": host_id,
                "start_time": start_time,
            },
        )

        rows = result.fetchall()

        if not timestamps:
            # First series: populate timestamps (as Unix epoch)
            timestamps = [int(row.bucket.timestamp()) for row in rows]
            uplot_data.append(timestamps)

        values = [float(row.avg_value) if row.avg_value is not None else None for row in rows]
        uplot_data.append(values)

    return {"data": uplot_data, "series": series}
