"""Heartbeat endpoint for agent health reporting."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update

from rp_server.database import DbSession
from rp_server.deps import TailscaleIdentity, tailscale_identity_optional
from rp_server.models import AgentVersion, Heartbeat, Host, CanaryDeploy
from rp_server.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    SelfCheckRequest,
    SelfCheckResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["heartbeat"])

OptionalTsIdentity = Annotated[TailscaleIdentity | None, Depends(tailscale_identity_optional)]


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def receive_heartbeat(
    request: HeartbeatRequest,
    db: DbSession,
    ts_identity: OptionalTsIdentity = None,
) -> HeartbeatResponse:
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
    stmt = update(Host).where(Host.id == request.host_id).values(last_seen_at=now)
    await db.execute(stmt)

    # Update agent version tracking (F8-3 compat)
    # Upsert agent_versions row
    agent_ver = AgentVersion(
        host_id=request.host_id,
        agent_version=request.agent_version,
        api_compat_min="0.1.0",  # TODO: Parse from Sec-RP-Min-Server header
        api_compat_max="1.0.0",  # TODO: Parse from Sec-RP-Agent-Version header
        last_check=now,
    )
    await db.merge(agent_ver)

    await db.commit()

    logger.debug(
        "Heartbeat received",
        extra={
            "host_id": str(request.host_id),
            "hostname": host.hostname,
            "cpu_pct": request.cpu_pct,
            "tailscale_login": ts_identity.login if ts_identity else None,
        },
    )

    # Record metrics
    from rp_server.metrics_exporter import record_heartbeat

    record_heartbeat(host.group_name or "default")

    return HeartbeatResponse(status="ok", server_ts=now)


# F8 - Agent upgrade endpoints


@router.post("/agent/self-check", response_model=SelfCheckResponse)
async def agent_self_check_report(
    request: SelfCheckRequest,
    db: DbSession,
) -> SelfCheckResponse:
    """Receive self-check report from agent post-upgrade.

    If upgrade_id present, updates canary deploy state.
    """
    logger.info(
        "Self-check report received",
        extra={
            "host_id": str(request.host_id),
            "agent_version": request.agent_version,
            "status": request.status,
            "upgrade_id": str(request.upgrade_id) if request.upgrade_id else None,
        },
    )

    canary_state_updated = False

    # If this is part of a canary deploy, update state
    if request.upgrade_id:
        stmt = select(CanaryDeploy).where(CanaryDeploy.id == request.upgrade_id)
        result = await db.execute(stmt)
        canary = result.scalar_one_or_none()

        if canary and canary.state == "pending":
            now = datetime.now(timezone.utc)

            if request.status == "ok":
                # Self-check passed, transition to observing
                canary.state = "observing"
                canary.canary_health_check_at = now
                canary_state_updated = True
                logger.info(
                    "Canary self-check passed, transitioning to observing",
                    extra={"canary_id": str(canary.id)},
                )
            else:
                # Self-check failed, mark as failed
                canary.state = "failed_rollback"
                canary.failed_reason = f"self_check_failed: {', '.join(request.errors)}"
                canary.completed_at = now
                canary_state_updated = True
                logger.error(
                    "Canary self-check failed",
                    extra={"canary_id": str(canary.id), "errors": request.errors},
                )

            await db.commit()

    return SelfCheckResponse(
        acknowledged=True,
        canary_state_updated=canary_state_updated,
    )


@router.post("/agent/version-handshake")
async def version_handshake(
    request: dict,
    db: DbSession,
) -> dict:
    """Receive version handshake from agent after upgrade.

    Updates agent_versions table.
    """
    host_id = request.get("host_id")
    agent_version = request.get("agent_version")
    api_compat_min = request.get("api_compat_min")
    api_compat_max = request.get("api_compat_max")

    if not all([host_id, agent_version, api_compat_min, api_compat_max]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields",
        )

    logger.info(
        "Version handshake received",
        extra={
            "host_id": host_id,
            "agent_version": agent_version,
            "api_compat_min": api_compat_min,
            "api_compat_max": api_compat_max,
        },
    )

    # Update agent_versions
    agent_ver = AgentVersion(
        host_id=host_id,
        agent_version=agent_version,
        api_compat_min=api_compat_min,
        api_compat_max=api_compat_max,
        last_check=datetime.now(timezone.utc),
    )
    await db.merge(agent_ver)
    await db.commit()

    return {"status": "ok"}


@router.post("/agent/rollback")
async def report_rollback(
    request: dict,
    db: DbSession,
) -> dict:
    """Receive rollback report from agent.

    Logs rollback event for audit trail.
    """
    host_id = request.get("host_id")
    from_version = request.get("from_version")
    to_version = request.get("to_version")
    reason = request.get("reason")

    logger.warning(
        "Agent rollback reported",
        extra={
            "host_id": host_id,
            "from_version": from_version,
            "to_version": to_version,
            "reason": reason,
        },
    )

    # Update agent_versions to reflect rollback
    if host_id and to_version:
        agent_ver = AgentVersion(
            host_id=host_id,
            agent_version=to_version,
            api_compat_min="0.1.0",  # Stub
            api_compat_max="1.0.0",  # Stub
            last_check=datetime.now(timezone.utc),
        )
        await db.merge(agent_ver)
        await db.commit()

    return {"status": "ok"}
