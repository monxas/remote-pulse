"""Metrics endpoints for sparkline data and available series."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text

from rp_server.database import DbSession
from rp_server.deps import TailscaleIdentity, tailscale_identity_optional
from rp_server.models import Host
from rp_server.schemas import SparklineResponse, SparklineSeries

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/metrics", tags=["metrics"])

OptionalTsIdentity = Annotated[TailscaleIdentity | None, Depends(tailscale_identity_optional)]

# Window to bucket mapping: maps time window strings to (duration_seconds, bucket_seconds)
# Designed to produce ~60 points per window for optimal sparkline rendering
WINDOW_BUCKET_MAP: dict[str, tuple[int, int]] = {
    "1m": (60, 1),  # 60 points at 1s resolution
    "5m": (300, 5),  # 60 points at 5s resolution
    "15m": (900, 15),  # 60 points at 15s resolution
    "1h": (3600, 60),  # 60 points at 1min resolution
    "6h": (21600, 360),  # 60 points at 6min resolution
    "24h": (86400, 1440),  # 60 points at 24min resolution
}

# Heartbeat metrics available from the heartbeats table
HEARTBEAT_METRICS = ["cpu_pct", "mem_pct", "load_1m", "uptime_s"]


@router.get("/{host_id}/sparkline", response_model=SparklineResponse)
async def get_sparkline_data(
    host_id: UUID,
    db: DbSession,
    series: list[str] = Query(
        default=["cpu_pct", "mem_pct"],
        description="Metrics to fetch (e.g. cpu_pct, mem_pct, load_1m)",
    ),
    window: str = Query(
        default="5m",
        description="Time window (1m, 5m, 15m, 1h, 6h, 24h)",
    ),
    max_points: int = Query(
        default=60,
        ge=10,
        le=200,
        description="Maximum points to return per series",
    ),
    ts_identity: OptionalTsIdentity = None,
) -> SparklineResponse:
    """
    Get sparkline time series data for specified metrics.

    F3: Queries heartbeats table for standard metrics using time_bucket aggregation.
    F3-extended TODO: Query metric_samples for custom metrics.

    Process:
    1. Validate host exists
    2. Validate window parameter
    3. Calculate bucket size based on window and max_points
    4. Query heartbeats table with time_bucket aggregation
    5. Return series data ordered by timestamp ascending
    """
    # Validate window
    if window not in WINDOW_BUCKET_MAP:
        valid_windows = ", ".join(WINDOW_BUCKET_MAP.keys())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid window '{window}'. Valid: {valid_windows}",
        )

    # Verify host exists
    stmt = select(Host).where(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found",
        )

    # Get window duration and default bucket
    window_seconds, bucket_seconds = WINDOW_BUCKET_MAP[window]

    # Calculate start time
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(seconds=window_seconds)

    # Collect series data
    series_data: list[SparklineSeries] = []

    for metric in series:
        # F3 simple: Only handle heartbeat metrics from heartbeats table
        if metric not in HEARTBEAT_METRICS:
            logger.warning(
                "Metric not in heartbeats table, skipping",
                extra={"metric": metric, "host_id": str(host_id)},
            )
            continue

        # Query heartbeats with time_bucket aggregation
        # Use time_bucket to group by bucket_seconds and avg() the metric
        query = text(
            f"""
            SELECT
                time_bucket(:bucket_interval, ts) AS bucket,
                avg({metric}) AS avg_value
            FROM heartbeats
            WHERE host_id = :host_id
                AND ts >= :start_time
                AND ts <= :end_time
                AND {metric} IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )

        result = await db.execute(
            query,
            {
                # asyncpg INTERVAL codec expects datetime.timedelta, not str
                "bucket_interval": timedelta(seconds=bucket_seconds),
                "host_id": host_id,
                "start_time": start_time,
                "end_time": now,
            },
        )

        rows = result.fetchall()

        # Convert to (timestamp, value) tuples
        points: list[tuple[datetime, float]] = [
            (row.bucket, float(row.avg_value)) for row in rows if row.avg_value is not None
        ]

        series_data.append(
            SparklineSeries(
                metric=metric,
                points=points,
            )
        )

    logger.debug(
        "Sparkline data fetched",
        extra={
            "host_id": str(host_id),
            "hostname": host.hostname,
            "window": window,
            "series_count": len(series_data),
            "tailscale_login": ts_identity.login if ts_identity else None,
        },
    )

    return SparklineResponse(
        host_id=host_id,
        window=window,
        series=series_data,
        bucket_seconds=bucket_seconds,
    )


@router.get("/{host_id}/series", response_model=list[str])
async def get_available_series(
    host_id: UUID,
    db: DbSession,
    ts_identity: OptionalTsIdentity = None,
) -> list[str]:
    """
    Get list of available metric series for a host.

    F3: Returns hardcoded list of heartbeat metrics.
    F3-extended TODO: Also fetch distinct metrics from metric_samples table.
    """
    # Verify host exists
    stmt = select(Host).where(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found",
        )

    # F3: Return hardcoded heartbeat metrics
    # F3-extended: Query SELECT DISTINCT metric FROM metric_samples WHERE host_id=...
    available = HEARTBEAT_METRICS.copy()

    logger.debug(
        "Available series fetched",
        extra={
            "host_id": str(host_id),
            "hostname": host.hostname,
            "series_count": len(available),
            "tailscale_login": ts_identity.login if ts_identity else None,
        },
    )

    return available
