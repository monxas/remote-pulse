"""Remote command issuance endpoints (F4-4).

Admin/operator endpoints for issuing signed commands to agents.
Commands stored in immutable audit log, agents poll for pending.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from rp_server.database import DbSession
from rp_server.deps import require_admin, require_operator_or_admin
from rp_server.events import fire_and_forget
from rp_server.models import CanaryDeploy, Command, Host, User
from rp_server.schemas import (
    CanaryStatus,
    CanaryUpgradeRequest,
    CanaryUpgradeResponse,
    CommandResponse,
)
from rp_server.signing import ServerSigningKey

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/admin", tags=["commands"])

# Module-level signing key (loaded once on import)
_signing_key: ServerSigningKey | None = None


def get_signing_key() -> ServerSigningKey:
    """Get or initialize server signing key.

    Returns:
        ServerSigningKey instance
    """
    global _signing_key
    if _signing_key is None:
        _signing_key = ServerSigningKey.load_or_generate()
    return _signing_key


class CommandCreate(BaseModel):
    """Command creation request."""

    host_id: uuid.UUID
    command_type: str = Field(
        min_length=1,
        max_length=50,
        examples=["exec_shell", "pkg_install", "service_restart"],
    )
    command_payload: dict[str, Any]
    timeout_s: int = Field(default=300, ge=1, le=3600, description="Execution timeout in seconds")
    expires_in_s: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Command signature validity window (default 60s per ADR-0008 §13)",
    )
    human_approved: bool = Field(
        default=False,
        description="Whether command has explicit human approval (Telegram flow F4-6)",
    )
    approved_by: str | None = Field(default=None, description="Approver identity if human_approved")


@router.post("/commands", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
async def create_command(
    request: CommandCreate,
    db: DbSession,
    user: Annotated[User, Depends(require_operator_or_admin)],
) -> CommandResponse:
    """Create and sign a remote command.

    Command is inserted into immutable audit log and signed with server's
    Ed25519 private key. Agent will verify signature before execution.

    Auth: operator+ role required.

    Args:
        request: Command creation parameters
        db: Database session
        user: Authenticated user (operator+)

    Returns:
        CommandResponse with signature included
    """
    issued_by = user.email

    # Verify host exists
    stmt = select(Host).where(Host.id == request.host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {request.host_id} not found",
        )

    # Generate command ID and expiration
    command_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.expires_in_s)

    # Sign command
    signing_key = get_signing_key()
    signature = signing_key.sign_command(
        command_id=str(command_id),
        command_type=request.command_type,
        payload=request.command_payload,
        expires_at=expires_at,
    )

    # Create command record (immutable audit log)
    command = Command(
        id=command_id,
        host_id=request.host_id,
        issued_by=issued_by,
        command_type=request.command_type,
        command_payload=request.command_payload,
        server_signature=signature,
        human_approved=request.human_approved,
        approved_by=request.approved_by,
    )

    db.add(command)
    await db.commit()
    await db.refresh(command)

    logger.info(
        "command created",
        command_id=str(command_id),
        host_id=str(request.host_id),
        hostname=host.hostname,
        command_type=request.command_type,
        expires_at=expires_at.isoformat(),
        human_approved=request.human_approved,
    )

    # ADR-0009 Phase 2: notify dashboards listening on /v1/dash/stream.
    fire_and_forget(
        "command.issued",
        {
            "command_id": str(command_id),
            "host_id": str(request.host_id),
            "group_name": host.group_name,
            "command_type": request.command_type,
            "issued_by": issued_by,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Convert to response schema
    return CommandResponse.model_validate(command)


@router.get("/commands", response_model=list[CommandResponse])
async def list_commands(
    db: DbSession,
    user: Annotated[User, Depends(require_operator_or_admin)],
    host_id: uuid.UUID | None = Query(default=None, description="Filter by host ID"),
    command_type: str | None = Query(default=None, description="Filter by command type"),
    completed: bool | None = Query(default=None, description="Filter by completion status"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results"),
) -> list[CommandResponse]:
    """List commands with optional filters.

    Auth: operator+ role required. Non-admin users only see commands for
    hosts in their accessible_groups.

    Args:
        db: Database session
        host_id: Optional host filter
        command_type: Optional command type filter
        completed: Optional completion status filter
        limit: Maximum number of results

    Returns:
        List of commands ordered by issued_at descending
    """
    # Build query
    stmt = select(Command).order_by(Command.issued_at.desc()).limit(limit)

    # Multi-tenant filtering: non-admins only see commands for accessible hosts
    if user.role != "admin":
        stmt = stmt.join(Host, Command.host_id == Host.id).where(
            Host.group_name.in_(user.accessible_groups)
        )

    if host_id:
        stmt = stmt.where(Command.host_id == host_id)

    if command_type:
        stmt = stmt.where(Command.command_type == command_type)

    if completed is not None:
        if completed:
            stmt = stmt.where(Command.completed_at.isnot(None))
        else:
            stmt = stmt.where(Command.completed_at.is_(None))

    result = await db.execute(stmt)
    commands = result.scalars().all()

    return [CommandResponse.model_validate(cmd) for cmd in commands]


@router.get("/commands/{command_id}", response_model=CommandResponse)
async def get_command(
    command_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(require_operator_or_admin)],
) -> CommandResponse:
    """Get single command by ID.

    Auth: operator+ role. Non-admin users can only see commands for hosts
    in their accessible_groups.
    """
    stmt = select(Command).where(Command.id == command_id)
    if user.role != "admin":
        stmt = stmt.join(Host, Command.host_id == Host.id).where(
            Host.group_name.in_(user.accessible_groups)
        )
    result = await db.execute(stmt)
    command = result.scalar_one_or_none()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command {command_id} not found",
        )

    return CommandResponse.model_validate(command)


# F8 - Canary deploy endpoints


@router.post(
    "/commands/canary-upgrade",
    response_model=CanaryUpgradeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_canary_upgrade(
    request: CanaryUpgradeRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_admin)],
) -> CanaryUpgradeResponse:
    """Initiate canary deploy upgrade.

    Auth: admin only.
    """
    issued_by = user.email

    # Select canary host
    if request.canary_host_id:
        # Use provided canary
        stmt = select(Host).where(Host.id == request.canary_host_id)
        result = await db.execute(stmt)
        canary_host = result.scalar_one_or_none()

        if not canary_host:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Canary host {request.canary_host_id} not found",
            )

        if canary_host.group_name != request.group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Canary host {canary_host.hostname} not in group {request.group}",
            )
    else:
        # Select lowest-criticality host in group
        # For now, just pick first host in group
        stmt = select(Host).where(Host.group_name == request.group).order_by(Host.hostname).limit(1)
        result = await db.execute(stmt)
        canary_host = result.scalar_one_or_none()

        if not canary_host:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No hosts found in group {request.group}",
            )

    # Create canary deploy record
    canary = CanaryDeploy(
        group_name=request.group,
        target_version=request.target_version,
        canary_host_id=canary_host.id,
        observation_minutes=request.observation_minutes,
        initiated_by=issued_by,
        state="pending",
    )
    db.add(canary)
    await db.commit()
    await db.refresh(canary)

    # Issue signed upgrade command to canary host
    signing_key = get_signing_key()
    command_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)

    payload = {
        "target_version": request.target_version,
        "canary_id": str(canary.id),
    }

    signature = signing_key.sign_command(
        command_id=str(command_id),
        command_type="agent_upgrade",
        payload=payload,
        expires_at=expires_at,
    )

    command = Command(
        id=command_id,
        host_id=canary_host.id,
        issued_by=issued_by,
        command_type="agent_upgrade",
        command_payload=payload,
        server_signature=signature,
        human_approved=False,
    )
    db.add(command)
    await db.commit()

    logger.info(
        "canary upgrade initiated",
        canary_id=str(canary.id),
        group=request.group,
        target_version=request.target_version,
        canary_host=canary_host.hostname,
        observation_minutes=request.observation_minutes,
    )

    # TODO F8: Start background observation task
    # For now, return response immediately

    # Count hosts in group for ETA
    stmt = select(func.count(Host.id)).where(Host.group_name == request.group)
    result = await db.execute(stmt)
    host_count = result.scalar() or 1

    eta_minutes = request.observation_minutes + (host_count * 2)  # ~2min per host

    return CanaryUpgradeResponse(
        canary_id=canary.id,
        target_version=request.target_version,
        canary_host_id=canary_host.id,
        canary_hostname=canary_host.hostname,
        group_name=request.group,
        observation_minutes=request.observation_minutes,
        eta_minutes=eta_minutes,
        state=canary.state,
    )


@router.get("/commands/canary-status/{canary_id}", response_model=CanaryStatus)
async def get_canary_status(
    canary_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(require_operator_or_admin)],
) -> CanaryStatus:
    """Get status of a canary deploy. Auth: operator+."""
    stmt = select(CanaryDeploy).where(CanaryDeploy.id == canary_id)
    result = await db.execute(stmt)
    canary = result.scalar_one_or_none()

    if not canary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Canary deploy {canary_id} not found",
        )

    # Get canary host info
    stmt = select(Host).where(Host.id == canary.canary_host_id)
    result = await db.execute(stmt)
    canary_host = result.scalar_one()

    # Count hosts in group
    stmt = select(func.count(Host.id)).where(Host.group_name == canary.group_name)
    result = await db.execute(stmt)
    total_hosts = result.scalar() or 0

    # Count upgraded hosts (stub - would query agent_versions table)
    hosts_upgraded = 1 if canary.state in ("propagating", "complete") else 0
    hosts_remaining = total_hosts - hosts_upgraded

    return CanaryStatus(
        id=canary.id,
        group_name=canary.group_name,
        target_version=canary.target_version,
        canary_host_id=canary.canary_host_id,
        canary_hostname=canary_host.hostname,
        state=canary.state,
        initiated_at=canary.initiated_at,
        observation_minutes=canary.observation_minutes,
        canary_health_check_at=canary.canary_health_check_at,
        propagation_started_at=canary.propagation_started_at,
        completed_at=canary.completed_at,
        failed_reason=canary.failed_reason,
        initiated_by=canary.initiated_by,
        hosts_remaining=hosts_remaining,
        hosts_upgraded=hosts_upgraded,
    )
