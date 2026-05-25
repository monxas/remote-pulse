"""API compatibility endpoints.

See ADR-0008 Appendix G for version negotiation policy.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from rp_server.compat import (
    API_FEATURES,
    SERVER_API_VERSION,
    SERVER_DEPRECATED_AGENT_VERSIONS,
    SERVER_MIN_AGENT_VERSION,
    is_version_compatible,
    is_version_deprecated,
)
from rp_server.database import DbSession
from rp_server.deps import require_admin
from rp_server.models import AgentVersion, User
from rp_server.schemas import CompatMatrixResponse, ServerInfoResponse

logger = structlog.get_logger()
router = APIRouter(tags=["compat"])


@router.get("/v1/server/info")
async def server_info() -> ServerInfoResponse:
    """Public endpoint (no auth) - agents call before connecting.

    Returns server version, minimum agent version, supported features,
    and service capabilities for compatibility negotiation.

    This endpoint is called by agents during bootstrap before they have
    enrolled or authenticated.
    """
    logger.debug("Server info requested")

    return ServerInfoResponse(
        server_version=SERVER_API_VERSION,
        api_version="v1",
        min_agent_version=SERVER_MIN_AGENT_VERSION,
        deprecated_agent_versions=SERVER_DEPRECATED_AGENT_VERSIONS,
        features=API_FEATURES,
        tailscale_ssh_supported=True,
        rustdesk_direct_ip_supported=True,
        sunshine_supported=True,
        max_metrics_window="1y",
        metrics_retention_policy={
            "heartbeat_raw": "90d",
            "metrics_downsampled_5m": "1y",
            "metrics_downsampled_1h": "5y",
        },
    )


@router.get("/v1/admin/compat-matrix")
async def compat_matrix(
    db: DbSession,
    user: Annotated[User, Depends(require_admin)],
) -> CompatMatrixResponse:
    """Get agent version distribution across fleet (admin only).

    Returns matrix showing:
    - Agent versions in use
    - Host count per version
    - Deprecation status
    - Compatibility status

    Useful for identifying hosts on outdated agents that require upgrade.
    """
    logger.info("Compat matrix requested", user_id=user.id, user_email=user.email)

    # Query agent version distribution
    stmt = (
        select(
            AgentVersion.agent_version,
            func.count(AgentVersion.host_id).label("host_count"),
        )
        .group_by(AgentVersion.agent_version)
        .order_by(AgentVersion.agent_version.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    entries = []
    total_hosts = 0

    for row in rows:
        version = row.agent_version
        count = row.host_count
        total_hosts += count

        deprecated = is_version_deprecated(version)
        compatible = is_version_compatible(version, SERVER_MIN_AGENT_VERSION)

        entries.append(
            {
                "agent_version": version,
                "host_count": count,
                "deprecated": deprecated,
                "compatible": compatible,
            }
        )

    return CompatMatrixResponse(
        server_version=SERVER_API_VERSION,
        min_agent_version=SERVER_MIN_AGENT_VERSION,
        entries=entries,
        total_hosts=total_hosts,
    )
