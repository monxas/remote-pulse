"""Remote command execution (stub for F4-4).

This module provides the integration point between server-issued commands
and local policy enforcement.
"""

from dataclasses import dataclass
from typing import Optional
import structlog

from rp.local_policy import LocalPolicy, CommandDecision, TelegramApprovalRequest

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


@dataclass
class CommandResult:
    """Result of command execution."""

    ack: bool
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    rejected_reason: Optional[str] = None


async def execute_remote_command(cmd: RemoteCommand) -> CommandResult:
    """Execute remote command with local-policy enforcement.

    This is a stub for F4-4. Currently implements only the local-policy
    pre-check layer.

    Args:
        cmd: Remote command to execute

    Returns:
        CommandResult with execution outcome

    Raises:
        NotImplementedError: Command execution not yet implemented (F4-4)
    """
    # Pre-execution local-policy check
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

    # ALLOW: actual execution will be implemented in F4-4
    logger.info(
        "command allowed by local policy (execution pending F4-4)",
        cmd_id=cmd.id,
        command_type=cmd.command_type,
    )
    raise NotImplementedError(
        f"Command execution not yet implemented (ticket F4-4): {cmd.command_type}"
    )
