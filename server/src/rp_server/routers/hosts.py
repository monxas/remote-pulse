"""Host inventory endpoints."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from rp_server.database import DbSession
from rp_server.deps import (
    TailscaleIdentity,
    current_user_optional,
    tailscale_identity_optional,
)
from rp_server.middleware.group_filter import filter_hosts_by_user_groups
from rp_server.models import Heartbeat, Host, User
from rp_server.schemas import HeartbeatData, HostDetail, HostListItem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["hosts"])

OptionalTsIdentity = Annotated[TailscaleIdentity | None, Depends(tailscale_identity_optional)]
OptionalUser = Annotated[User | None, Depends(current_user_optional)]


@router.get("/hosts", response_model=list[HostListItem])
async def list_hosts(
    db: DbSession,
    user: OptionalUser = None,
    ts_identity: OptionalTsIdentity = None,
) -> list[HostListItem]:
    """List all registered hosts.

    Dual-mode auth:
    - Tailscale identity (agent or admin via tailnet): full visibility
    - PocketID web user (via Caddy forward_auth): filtered by accessible_groups
    - Neither: 401

    Multi-tenant: non-admin web users see only hosts whose group_name is in
    their accessible_groups list.
    """
    if user is None and ts_identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    stmt = select(Host).order_by(Host.hostname)
    if user is not None:
        stmt = filter_hosts_by_user_groups(stmt, user)
    result = await db.execute(stmt)
    hosts = result.scalars().all()

    return [HostListItem.model_validate(host) for host in hosts]


@router.get("/hosts/{host_id}", response_model=HostDetail)
async def get_host_detail(
    host_id: uuid.UUID,
    db: DbSession,
    user: OptionalUser = None,
    ts_identity: OptionalTsIdentity = None,
) -> HostDetail:
    """Get detailed host info including recent heartbeats.

    Dual-mode auth (see list_hosts). Non-admin web users only see hosts in
    their accessible_groups; otherwise 404 (avoid leaking host existence).
    """
    if user is None and ts_identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    stmt = select(Host).where(Host.id == host_id)
    if user is not None:
        stmt = filter_hosts_by_user_groups(stmt, user)
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
