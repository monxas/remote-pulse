"""Scheduled task for cleaning up expired approval tokens.

F4-6: Auto-rejects commands with approval_token older than TTL (default 5min).
Runs every 1 minute as background task in server.
"""

import structlog
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from rp_server.database import get_async_session
from rp_server.models import Command

logger = structlog.get_logger()


async def cleanup_expired_approvals(ttl_minutes: int = 5) -> int:
    """Clean up expired approval tokens.

    Finds commands with approval_token set where approval_requested_at is
    older than TTL, marks them as rejected with timeout reason.

    Args:
        ttl_minutes: Approval TTL in minutes (default 5)

    Returns:
        Number of commands auto-rejected
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)

    async with get_async_session() as db:
        # Find expired pending approvals
        stmt = select(Command).where(
            and_(
                Command.approval_token.isnot(None),
                Command.approval_requested_at < cutoff,
                Command.human_approved == False,  # noqa: E712
                Command.rejected_reason.is_(None),
            )
        )

        result = await db.execute(stmt)
        commands = result.scalars().all()

        if not commands:
            return 0

        # Mark as rejected
        count = 0
        for command in commands:
            command.rejected_reason = "approval_timeout"
            command.approval_token = None  # Clear token
            count += 1

            logger.info(
                "approval expired, auto-rejected",
                command_id=str(command.id),
                command_type=command.command_type,
                age_minutes=(
                    datetime.now(timezone.utc)
                    - command.approval_requested_at.replace(tzinfo=timezone.utc)
                ).total_seconds()
                / 60,
            )

        await db.commit()

        logger.info("approval cleanup completed", expired_count=count)
        return count


async def run_approval_cleanup_loop(interval_seconds: int = 60, ttl_minutes: int = 5):
    """Run cleanup loop as background task.

    Args:
        interval_seconds: Cleanup interval in seconds (default 60)
        ttl_minutes: Approval TTL in minutes (default 5)
    """
    import asyncio

    logger.info(
        "approval cleanup loop started",
        interval_seconds=interval_seconds,
        ttl_minutes=ttl_minutes,
    )

    while True:
        try:
            await cleanup_expired_approvals(ttl_minutes)
        except Exception as e:
            logger.error("approval cleanup failed", error=str(e), exc_info=True)

        await asyncio.sleep(interval_seconds)
