"""Remote command execution (stub for F4-4).

This module provides the integration point between server-issued commands
and local policy enforcement.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import structlog

from rp.local_policy import LocalPolicy, CommandDecision, TelegramApprovalRequest
from rp.replay_guard import ReplayGuard
from rp.signature import ServerTrust

logger = structlog.get_logger()


@dataclass
class RemoteCommand:
    """Remote command from server."""

    id: str
    command_type: str
    payload: dict
    target_group: str
    issued_by: str
    server_signature: str
    expires_at: datetime


@dataclass
class CommandResult:
    """Result of command execution."""

    ack: bool
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    rejected_reason: Optional[str] = None


async def execute_remote_command(cmd: RemoteCommand) -> CommandResult:
    """Execute remote command with signature + local-policy enforcement.

    Defense-in-depth layers:
    1. Server signature verification (cryptographic trust)
    2. Local policy check (defense against server compromise)
    3. Optional Telegram approval (human-in-loop for destructive ops)

    Args:
        cmd: Remote command to execute

    Returns:
        CommandResult with execution outcome

    Raises:
        NotImplementedError: Command execution not yet implemented (F4-4)
    """
    # Layer 1: Verify server signature FIRST
    trust = ServerTrust.load()
    if not trust:
        logger.error(
            "no server trust anchor",
            cmd_id=cmd.id,
            command_type=cmd.command_type,
        )
        return CommandResult(ack=False, rejected_reason="no_server_trust_anchor")

    if not trust.verify_command(
        command_id=cmd.id,
        command_type=cmd.command_type,
        payload=cmd.payload,
        expires_at=cmd.expires_at,
        signature_b64=cmd.server_signature,
    ):
        logger.warning(
            "signature verification FAILED",
            cmd_id=cmd.id,
            command_type=cmd.command_type,
            fingerprint=trust.fingerprint,
        )
        return CommandResult(ack=False, rejected_reason="signature_invalid")

    # Layer 1b: Replay protection (review M3). Even with a valid signature, an
    # attacker who captures the blob could resend it within its 60s expiry
    # window. We refuse to execute the same command_id twice.
    replay_guard = ReplayGuard()
    if replay_guard.has_seen(cmd.id):
        logger.warning(
            "replay attempt rejected",
            cmd_id=cmd.id,
            command_type=cmd.command_type,
        )
        return CommandResult(ack=False, rejected_reason="replay_detected")

    # Layer 2: Local-policy check (defense against server compromise per ADR-0008 §13)
    policy = LocalPolicy()
    decision, reason = policy.evaluate(cmd.command_type, cmd.payload, cmd.target_group)

    logger.info(
        "local policy decision",
        cmd_id=cmd.id,
        command_type=cmd.command_type,
        decision=decision,
        reason=reason,
    )

    if decision == CommandDecision.DENY:
        logger.warning(
            "local policy DENIED command",
            cmd_id=cmd.id,
            command_type=cmd.command_type,
            reason=reason,
        )
        return CommandResult(ack=False, rejected_reason=f"local_policy_deny: {reason}")

    if decision == CommandDecision.REQUIRE_APPROVAL:
        # F4-6 will hook into Telegram approval flow
        logger.info(
            "command requires Telegram approval",
            cmd_id=cmd.id,
            command_type=cmd.command_type,
        )

        approval = TelegramApprovalRequest(
            command_id=cmd.id,
            command_type=cmd.command_type,
            reason=reason,
        )

        try:
            approved = await approval.wait_for_decision(timeout_s=300)
            if not approved:
                return CommandResult(
                    ack=False, rejected_reason="telegram_approval_rejected"
                )
        except NotImplementedError:
            # F4-6 not implemented yet
            logger.error("Telegram approval flow not available (F4-6)")
            return CommandResult(
                ack=False,
                rejected_reason="telegram_approval_not_implemented",
            )

    # ALLOW: actual execution will be implemented in F4-4.
    # Mark command as seen for replay protection BEFORE executing so a crash
    # mid-execution cannot be exploited to retry the same payload.
    replay_guard.mark_executed(cmd.id)

    logger.info(
        "command allowed by local policy (execution pending F4-4)",
        cmd_id=cmd.id,
        command_type=cmd.command_type,
    )
    raise NotImplementedError(
        f"Command execution not yet implemented (ticket F4-4): {cmd.command_type}"
    )
