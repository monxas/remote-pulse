"""Host inventory endpoints."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from rp_server.database import DbSession
from rp_server.deps import TailscaleIdentity, tailscale_identity_optional
from rp_server.models import Heartbeat, Host
from rp_server.schemas import HeartbeatData, HostDetail, HostListItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["hosts"])

OptionalTsIdentity = Annotated[TailscaleIdentity | None, Depends(tailscale_identity_optional)]


@router.get("/hosts", response_model=list[HostListItem])
async def list_hosts(
    db: DbSession,
    ts_identity: OptionalTsIdentity = None,
) -> list[HostListItem]:
    """
    List all registered hosts with summary information.

    Returns basic host info and last_seen_at for quick status overview.
    F5 TODO: Filter by user's accessible_groups for multi-tenant access.
    """
    stmt = select(Host).order_by(Host.hostname)
    result = await db.execute(stmt)
    hosts = result.scalars().all()

    return [HostListItem.model_validate(host) for host in hosts]


@router.get("/hosts/{host_id}", response_model=HostDetail)
async def get_host_detail(
    host_id: uuid.UUID,
    db: DbSession,
    ts_identity: OptionalTsIdentity = None,
) -> HostDetail:
    """
    Get detailed host information including recent heartbeats.

    Returns:
        Host detail with last 100 heartbeats ordered by timestamp descending.

    F5 TODO: Verify user has access to this host's group.
    """
    # Get host
    stmt = select(Host).where(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found",
        )

    # Get recent heartbeats (last 100)
    stmt = (
        select(Heartbeat)
        .where(Heartbeat.host_id == host_id)
        .order_by(Heartbeat.ts.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    heartbeats = result.scalars().all()

    recent_heartbeats = [HeartbeatData.model_validate(hb) for hb in heartbeats]

    return HostDetail(
        id=host.id,
        hostname=host.hostname,
        fqdn=host.fqdn,
        tailscale_node_id=host.tailscale_node_id,
        os=host.os,
        arch=host.arch,
        distro=host.distro,
        agent_version=host.agent_version,
        enrolled_at=host.enrolled_at,
        last_seen_at=host.last_seen_at,
        group_name=host.group_name,
        capabilities=host.capabilities,
        metadata=host.extra,
        recent_heartbeats=recent_heartbeats,
    )
