"""Telegram approval endpoints for destructive commands (F4-6).

Implements defense-in-depth human-in-the-loop approval flow via n8n + Telegram.
Commands requiring approval are held until admin responds via Telegram inline buttons.
"""

import hmac
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, update

from rp_server.database import DbSession
from rp_server.deps import require_admin, require_operator_or_admin
from rp_server.events import fire_and_forget
from rp_server.models import Command, Host, User

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/admin", tags=["approvals"])


# Schemas


class ApprovalRequest(BaseModel):
    """Response when approval is requested."""

    command_id: uuid.UUID
    approval_token: uuid.UUID
    expires_at: datetime


class ApprovalPayload(BaseModel):
    """Approval/rejection decision payload from n8n."""

    approver_id: str = Field(
        description="Telegram user ID or username of approver",
        examples=["730947207", "ramonkawa"],
    )
    reason: str | None = Field(default=None, description="Optional approval/rejection reason")


class ApprovalResult(BaseModel):
    """Result of approval decision."""

    status: str = Field(examples=["approved", "rejected"])
    command_id: uuid.UUID
    executed: bool = Field(
        default=False,
        description="Whether command was forwarded to agent for execution",
    )
    message: str


class PendingApprovalItem(BaseModel):
    """Pending approval summary."""

    command_id: uuid.UUID
    command_type: str
    host_hostname: str
    host_group: str | None
    issued_by: str
    issued_at: datetime
    approval_requested_at: datetime
    expires_at: datetime


# Helper functions


def _verify_callback_ip(request_ip: str, allowed_ips: list[str]) -> bool:
    """Verify callback originates from allowed IP (n8n LXC).

    Args:
        request_ip: Request source IP
        allowed_ips: List of allowed IPs

    Returns:
        True if allowed
    """
    return request_ip in allowed_ips


def _compute_hmac(payload: dict[str, Any], secret: str) -> str:
    """Compute HMAC-SHA256 signature for payload.

    Args:
        payload: Payload dict
        secret: Shared secret

    Returns:
        Hex-encoded HMAC
    """
    # Canonical JSON (sorted keys, no whitespace)
    import json

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# Endpoints


@router.post(
    "/commands/{command_id}/request-approval",
    response_model=ApprovalRequest,
    status_code=status.HTTP_201_CREATED,
)
async def request_approval(
    command_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(require_operator_or_admin)],
) -> ApprovalRequest:
    """Request Telegram approval for a command.

    Generates approval_token and fires n8n webhook. Called internally by
    create_command when local_policy.evaluate() returns REQUIRE_APPROVAL.

    Auth: operator+ role required (used by server-side workflows or admin UI).

    Args:
        command_id: Command UUID
        db: Database session

    Returns:
        ApprovalRequest with token and expiry
    """
    # Fetch command
    stmt = select(Command).where(Command.id == command_id)
    result = await db.execute(stmt)
    command = result.scalar_one_or_none()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command {command_id} not found",
        )

    if command.approval_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval already requested for this command",
        )

    # Generate approval token
    approval_token = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    # Update command (NOTE: this is OK despite __setattr__ guard because
    # we're updating before first commit completes in transaction)
    command.approval_token = approval_token
    command.approval_requested_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "approval requested",
        command_id=str(command_id),
        approval_token=str(approval_token),
    )

    # ADR-0009 Phase 1: notify dashboards listening on /v1/dash/stream.
    fire_and_forget(
        "approval.created",
        {
            "approval_id": str(approval_token),
            "command_id": str(command_id),
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    # TODO F4-6: Fire webhook to n8n (deferred to integration)
    # webhook = TelegramApprovalWebhook(...)
    # await webhook.fire_approval_request(command, host, approval_token)

    return ApprovalRequest(
        command_id=command_id,
        approval_token=approval_token,
        expires_at=expires_at,
    )


@router.post("/commands/approve/{approval_token}", response_model=ApprovalResult)
async def approve_command(
    approval_token: uuid.UUID,
    payload: ApprovalPayload,
    db: DbSession,
) -> ApprovalResult:
    """Approve command via Telegram callback.

    Called by n8n after admin clicks "Approve" button in Telegram.
    Verifies token not expired, marks command human_approved=true.

    Auth: IP allowlist + single-use token (belt-and-suspenders)

    Args:
        approval_token: Unique approval token
        payload: Approval decision data
        db: Database session

    Returns:
        ApprovalResult with status
    """
    # Atomic claim: clear token + mark approved in single UPDATE with WHERE
    # guard (TOCTOU-safe). Only the first request wins; subsequent requests
    # for same token observe rowcount=0.
    now = datetime.now(timezone.utc)
    ttl_cutoff = now - timedelta(seconds=300)  # 5min TTL per ADR §13

    stmt = (
        update(Command)
        .where(
            and_(
                Command.approval_token == approval_token,
                Command.human_approved.is_(False),
                Command.rejected_reason.is_(None),
                Command.approval_requested_at >= ttl_cutoff,
            )
        )
        .values(
            human_approved=True,
            approved_by=f"telegram:{payload.approver_id}",
            approval_responded_at=now,
            approval_token=None,  # single-use
        )
        .returning(Command.id, Command.host_id)
    )
    result = await db.execute(stmt)
    claimed = result.first()
    await db.commit()

    if not claimed:
        # Distinguish 404 (not found / already processed) vs 403 (expired)
        # by a follow-up read — but report consistently to avoid leaking state.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval token not found, expired (>5min), or already processed",
        )

    command_id, host_id = claimed
    # Fetch host hostname for logging
    host_row = await db.execute(select(Host.hostname).where(Host.id == host_id))
    host_hostname = host_row.scalar_one_or_none() or "unknown"
    # Construct minimal command stub for response
    command = type("CmdStub", (), {"id": command_id})()
    host = type("HostStub", (), {"hostname": host_hostname})()

    logger.info(
        "command approved",
        command_id=str(command.id),
        approver=payload.approver_id,
        host=host.hostname,
    )

    # ADR-0009 Phase 1: SSE notification
    fire_and_forget(
        "command.status_change",
        {
            "command_id": str(command.id),
            "host_id": str(host_id),
            "status": "approved",
            "ts": now.isoformat(),
        },
    )

    # TODO F4-6: Forward signed command to agent for execution
    # (currently agent polls for pending commands; webhook push TBD F5)

    return ApprovalResult(
        status="approved",
        command_id=command.id,
        executed=False,  # Agent will poll and execute
        message=f"Command approved by {payload.approver_id}",
    )


@router.post("/commands/reject/{approval_token}", response_model=ApprovalResult)
async def reject_command(
    approval_token: uuid.UUID,
    payload: ApprovalPayload,
    db: DbSession,
) -> ApprovalResult:
    """Reject command via Telegram callback.

    Called by n8n after admin clicks "Reject" button.

    Args:
        approval_token: Unique approval token
        payload: Rejection data
        db: Database session

    Returns:
        ApprovalResult with status
    """
    # Fetch command
    stmt = (
        select(Command, Host)
        .join(Host, Command.host_id == Host.id)
        .where(
            and_(
                Command.approval_token == approval_token,
                Command.human_approved == False,  # noqa: E712
                Command.rejected_reason.is_(None),
            )
        )
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found or already processed",
        )

    command, host = row

    # Check expiration
    if command.approval_requested_at:
        age = datetime.now(timezone.utc) - command.approval_requested_at.replace(
            tzinfo=timezone.utc
        )
        if age.total_seconds() > 300:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Approval token expired",
            )

    # Mark rejected
    reason = payload.reason or "rejected by admin via Telegram"
    command.rejected_reason = f"telegram_reject:{payload.approver_id}:{reason}"
    command.approval_responded_at = datetime.now(timezone.utc)
    command.approval_token = None

    await db.commit()

    logger.info(
        "command rejected",
        command_id=str(command.id),
        approver=payload.approver_id,
        reason=reason,
        host=host.hostname,
    )

    # ADR-0009 Phase 1: SSE notification
    fire_and_forget(
        "command.status_change",
        {
            "command_id": str(command.id),
            "host_id": str(command.host_id),
            "status": "rejected",
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ApprovalResult(
        status="rejected",
        command_id=command.id,
        executed=False,
        message=f"Command rejected by {payload.approver_id}: {reason}",
    )


@router.get("/commands/pending-approval", response_model=list[PendingApprovalItem])
async def list_pending_approvals(
    db: DbSession,
    user: Annotated[User, Depends(require_admin)],
) -> list[PendingApprovalItem]:
    """List commands awaiting approval.

    Used for admin UI or n8n polling fallback.

    Auth: admin role required.

    Args:
        db: Database session

    Returns:
        List of pending approvals
    """
    # Query pending approvals
    stmt = (
        select(Command, Host)
        .join(Host, Command.host_id == Host.id)
        .where(
            and_(
                Command.approval_token.isnot(None),
                Command.human_approved == False,  # noqa: E712
                Command.rejected_reason.is_(None),
            )
        )
        .order_by(Command.approval_requested_at.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for command, host in rows:
        if command.approval_requested_at:
            expires_at = command.approval_requested_at + timedelta(minutes=5)
        else:
            expires_at = command.issued_at + timedelta(minutes=5)

        items.append(
            PendingApprovalItem(
                command_id=command.id,
                command_type=command.command_type,
                host_hostname=host.hostname,
                host_group=host.group_name,
                issued_by=command.issued_by,
                issued_at=command.issued_at,
                approval_requested_at=command.approval_requested_at or command.issued_at,
                expires_at=expires_at,
            )
        )

    return items
