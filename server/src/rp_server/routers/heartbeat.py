"""Heartbeat endpoint for agent health reporting."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from rp_server.database import DbSession
from rp_server.models import Heartbeat, Host
from rp_server.schemas import HeartbeatRequest, HeartbeatResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["heartbeat"])


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def receive_heartbeat(request: HeartbeatRequest, db: DbSession) -> HeartbeatResponse:
    """
    Receive agent heartbeat with metrics.

    Process:
    1. Verify host_id exists
    2. Insert heartbeat record with server timestamp as source of truth
    3. Update host.last_seen_at
    4. Return server timestamp for clock skew detection

    F1: No authentication enforcement (HTTP plaintext LAN).
    F2 TODO: Verify Tailscale identity matches host ownership.
    F3 TODO: Check for clock skew (abs(server_ts - agent_ts) > 120s) and alert.
    """
    # Verify host exists
    stmt = select(Host).where(Host.id == request.host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {request.host_id} not found",
        )

    now = datetime.now(timezone.utc)

    # Insert heartbeat
    heartbeat = Heartbeat(
        host_id=request.host_id,
        ts=now,  # Server timestamp is source of truth
        agent_ts=request.agent_ts,
        cpu_pct=request.cpu_pct,
        mem_pct=request.mem_pct,
        load_1m=request.load_1m,
        uptime_s=request.uptime_s,
        agent_version=request.agent_version,
    )

    db.add(heartbeat)

    # Update host last_seen
    stmt = (
        update(Host)
        .where(Host.id == request.host_id)
        .values(last_seen_at=now)
    )
    await db.execute(stmt)

    await db.commit()

    logger.debug(
        "Heartbeat received",
        extra={
            "host_id": str(request.host_id),
            "hostname": host.hostname,
            "cpu_pct": request.cpu_pct,
        },
    )

    return HeartbeatResponse(status="ok", server_ts=now)
