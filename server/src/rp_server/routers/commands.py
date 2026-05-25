"""Remote command issuance endpoints (F4-4).

Admin/operator endpoints for issuing signed commands to agents.
Commands stored in immutable audit log, agents poll for pending.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from rp_server.database import DbSession
from rp_server.models import Command, Host
from rp_server.schemas import CommandResponse
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
async def create_command(request: CommandCreate, db: DbSession) -> CommandResponse:
    """Create and sign a remote command.

    Command is inserted into immutable audit log and signed with server's
    Ed25519 private key. Agent will verify signature before execution.

    Auth: TODO F5 - requires admin/operator role (stub for now)

    Args:
        request: Command creation parameters
        db: Database session

    Returns:
        CommandResponse with signature included
    """
    # TODO F5: Add role-based auth check here
    # For now, stub with hardcoded "admin" issuer
    issued_by = "admin"  # Will be replaced with TsIdentity.user_login in F5

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

    # Convert to response schema
    return CommandResponse.model_validate(command)


@router.get("/commands", response_model=list[CommandResponse])
async def list_commands(
    db: DbSession,
    host_id: uuid.UUID | None = Query(default=None, description="Filter by host ID"),
    command_type: str | None = Query(default=None, description="Filter by command type"),
    completed: bool | None = Query(default=None, description="Filter by completion status"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results"),
) -> list[CommandResponse]:
    """List commands with optional filters.

    Auth: TODO F5 - requires admin/operator role

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
async def get_command(command_id: uuid.UUID, db: DbSession) -> CommandResponse:
    """Get single command by ID.

    Auth: TODO F5 - requires admin/operator role

    Args:
        command_id: Command UUID
        db: Database session

    Returns:
        Command details
    """
    stmt = select(Command).where(Command.id == command_id)
    result = await db.execute(stmt)
    command = result.scalar_one_or_none()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command {command_id} not found",
        )

    return CommandResponse.model_validate(command)
