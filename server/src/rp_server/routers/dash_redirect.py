"""Legacy ``/dash/*`` redirect shim (ADR-0009 Phase 3 cutover).

The Jinja+HTMX dashboard previously served at ``/dash/*`` has been replaced
by the SvelteKit SPA mounted at ``/dash-next/*``. This router answers any
remaining ``/dash/...`` request with a 302 redirect to the SPA equivalent
so bookmarks, links from emails, and any out-of-tree references keep
working through the cutover.

Two things are *not* redirected:

* ``GET /dash/host/{host_id}/sparkline-data`` — still consumed by external
  clients / older builds; preserved here verbatim until they migrate to
  ``/v1/dash/hosts/{id}/timeseries``.
* (Nothing else.) The catch-all redirect handles ``/dash``, ``/dash/``,
  ``/dash/hosts``, ``/dash/commands``, ``/dash/host/{id}``, and any
  unknown sub-path.

Path + query string are preserved across the redirect: a request to
``/dash/host/abc?tab=metrics`` becomes ``/dash-next/hosts/abc?tab=metrics``.
The path mapping table below covers the only sub-paths the old Jinja UI
actually exposed; everything else falls back to ``/dash-next/``.

The old ``web.router`` is no longer mounted in ``main.py``. The router
module is kept on disk for one more release for easy rollback and will
be deleted in a follow-up cleanup commit.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text

from rp_server.database import DbSession
from rp_server.deps import current_user
from rp_server.middleware.group_filter import filter_hosts_by_user_groups
from rp_server.models import Host, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dash", tags=["web-legacy"])


# --------------------------------------------------------------------------- #
# Path mapping (legacy Jinja path -> SPA path)
# --------------------------------------------------------------------------- #
#
# Order matters: the first regex that matches wins. ``rest`` is the captured
# remainder appended (with separator already accounted for). The catch-all
# at the bottom guarantees every request resolves to *something* under
# ``/dash-next/``.

_HOST_UUID_RE = re.compile(
    r"^host/(?P<id>[0-9a-fA-F-]{8,})(?P<rest>/.*)?$"
)


def _map_legacy_path_to_spa(subpath: str) -> str:
    """Translate the path *after* the ``/dash/`` prefix to a SPA path.

    The returned value already starts with ``/dash-next`` (no trailing slash
    unless the input demanded it). Query string handling is done by the
    caller — this function only deals with the path component.
    """
    # Normalize: drop leading slash so each branch deals with a bare segment
    s = subpath.lstrip("/")

    # Root: /dash or /dash/  -> /dash-next/
    if s == "":
        return "/dash-next/"

    # /dash/hosts(/refresh)? -> /dash-next/hosts
    if s == "hosts" or s == "hosts/" or s.startswith("hosts/refresh"):
        return "/dash-next/hosts"

    # /dash/host/{uuid}(/...)? -> /dash-next/hosts/{uuid}
    m = _HOST_UUID_RE.match(s)
    if m:
        host_id = m.group("id")
        return f"/dash-next/hosts/{host_id}"

    # Top-level SPA sections that have direct equivalents.
    for section in ("commands", "approvals", "audit", "enroll", "settings"):
        if s == section or s == f"{section}/" or s.startswith(f"{section}/"):
            return f"/dash-next/{section}"

    # /dash/enroll-link(/...) — the old magic-link surface lives under the
    # SPA Enroll page now.
    if s.startswith("enroll-link"):
        return "/dash-next/enroll"

    # Fallback: send to SPA root and let client-side router decide.
    return "/dash-next/"


def _redirect_to_spa(request: Request, subpath: str) -> RedirectResponse:
    """Build a 302 redirect that preserves the original query string."""
    target = _map_legacy_path_to_spa(subpath)
    query = request.url.query
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


# --------------------------------------------------------------------------- #
# Preserved endpoint: sparkline-data
# --------------------------------------------------------------------------- #
#
# Defined *before* the catch-all so FastAPI's route matcher picks it first.
# Body is a verbatim copy of the original ``web.py`` implementation; the
# new ``/v1/dash/hosts/{id}/timeseries`` endpoint serves the same data in
# a slightly different shape, but we keep this around until external
# consumers cut over.


@router.get("/host/{host_id}/sparkline-data")
async def sparkline_data_json(
    host_id: UUID,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    series: list[str] = Query(default=["cpu_pct", "mem_pct"]),
    window: str = Query(default="5m"),
):
    """JSON endpoint for uPlot sparkline data (legacy, kept for cutover)."""
    stmt = select(Host).where(Host.id == host_id)
    stmt = filter_hosts_by_user_groups(stmt, user)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Host not found or access denied",
        )

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

    uplot_data: list = []
    timestamps: list[int] = []

    ALLOWED_METRICS = {"cpu_pct", "mem_pct", "load_1m", "uptime_s"}
    for metric in series:
        if metric not in ALLOWED_METRICS:
            continue
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
            timestamps = [int(row.bucket.timestamp()) for row in rows]
            uplot_data.append(timestamps)

        values = [float(row.avg_value) if row.avg_value is not None else None for row in rows]
        uplot_data.append(values)

    return {"data": uplot_data, "series": series}


# --------------------------------------------------------------------------- #
# Catch-all redirect
# --------------------------------------------------------------------------- #
#
# Two routes — the bare prefix and the wildcard — because FastAPI's path
# converter doesn't match the empty segment on the prefix root.


@router.get("/", include_in_schema=False)
async def dash_root_redirect(request: Request) -> RedirectResponse:
    """Redirect ``GET /dash/`` (and ``/dash``) to the SPA root."""
    return _redirect_to_spa(request, "")


@router.get("/{subpath:path}", include_in_schema=False)
async def dash_catchall_redirect(
    request: Request,
    subpath: str,
) -> RedirectResponse:
    """Redirect every other ``/dash/...`` request to its SPA equivalent."""
    return _redirect_to_spa(request, subpath)
