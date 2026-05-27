"""Audit log retention — periodic GC for ``audit_events``.

The ``audit_events`` table is append-only by design (immutability is
enforced at the DB layer; see alembic 008 + the
``test_audit_log_immutability`` suite). That means we can never UPDATE
or rewrite rows — but we *can* DELETE old ones, and we need to or the
table grows without bound.

This module owns three concerns:

1. The singleton :class:`AuditRetentionConfig` row CRUD helpers
   (``get_config``, ``upsert_config``). The migration seeds the row, but
   the helpers tolerate its absence in case somebody nukes it manually.
2. The actual purge query (``purge_old_audit_events``). One ``DELETE …
   RETURNING id`` against the indexed ``ts`` column; updates the
   ``last_purge_at`` + ``last_purge_count`` book-keeping fields on the
   config row in the same transaction.
3. The background scheduler (``retention_loop``). A plain asyncio task
   that wakes every 24h. We deliberately did NOT pull in APScheduler:
   the dispatcher and the rest of the server already have hand-rolled
   ``asyncio.create_task`` lifecycles (see ``rp_server.webhooks``), and
   adding a framework for a single 24h tick would be overkill.

Why DELETE … RETURNING and not TRUNCATE / partitioning
------------------------------------------------------
At homelab scale, even with a noisy fleet, ``audit_events`` is in the
tens-of-thousands-per-quarter range. A range DELETE against an indexed
column hits the index and runs in milliseconds. Partitioning by
timestamp would be the right call at millions-per-day; we're not there
and may never be. If the table ever does explode, this module is the
obvious choke-point to swap in a smarter strategy.

Why no DB-side scheduler (pg_cron / TimescaleDB retention policy)
-----------------------------------------------------------------
Both would work, but they'd take the operator's eyes off the policy:
the admin would have to read a cron table or a TimescaleDB function to
know what's running. Keeping the loop in-process means the same admin
UI that mutates the config also controls the lifecycle, and the audit
row for "config changed" + the metric for "rows deleted" tell the whole
story without leaving the app.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rp_server.models import AuditEvent, AuditRetentionConfig

if TYPE_CHECKING:  # pragma: no cover - typing-only
    pass


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #
#
# A week is the floor: anything less and an admin investigating a
# Friday-night incident on Monday could lose the trail. A decade is the
# ceiling: longer than that and we're effectively disabling retention,
# in which case the operator should just toggle ``enabled=false``
# instead of setting a ridiculous number.

MIN_RETENTION_DAYS = 7
MAX_RETENTION_DAYS = 3650
DEFAULT_RETENTION_DAYS = 90

# The scheduler tick. 24h is the natural cadence — daily granularity is
# plenty for a retention policy measured in weeks-to-years, and a longer
# tick risks the admin clicking "Purge now" because they "weren't sure
# if it was running".
RETENTION_LOOP_INTERVAL_SECONDS = 24 * 3600


# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #


async def get_config(db: AsyncSession) -> AuditRetentionConfig:
    """Return the singleton config row, creating it if missing.

    The migration seeds the row on upgrade, but we don't assume it: a
    fresh DB before migration, or a manual DELETE, both leave the table
    empty. In either case we synthesise a default row so the rest of
    the codepath has something to read.
    """
    row = (
        await db.execute(select(AuditRetentionConfig).where(AuditRetentionConfig.id == 1))
    ).scalar_one_or_none()
    if row is None:
        row = AuditRetentionConfig(
            id=1,
            retention_days=DEFAULT_RETENTION_DAYS,
            enabled=True,
            updated_by="system",
        )
        db.add(row)
        await db.flush()
    return row


async def update_config(
    db: AsyncSession,
    *,
    actor: str,
    retention_days: int | None = None,
    enabled: bool | None = None,
) -> AuditRetentionConfig:
    """Patch the singleton config; validates bounds.

    The caller is expected to commit the surrounding transaction — we
    flush so the changes are visible to the returned object but stop
    short of committing so the same transaction can also emit an
    ``audit.retention.config_updated`` row atomically with the change.
    """
    row = await get_config(db)

    if retention_days is not None:
        if (
            retention_days < MIN_RETENTION_DAYS
            or retention_days > MAX_RETENTION_DAYS
        ):
            raise ValueError(
                f"retention_days must be between {MIN_RETENTION_DAYS} "
                f"and {MAX_RETENTION_DAYS} (got {retention_days})"
            )
        row.retention_days = retention_days

    if enabled is not None:
        row.enabled = enabled

    row.updated_by = actor
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return row


# --------------------------------------------------------------------------- #
# Purge
# --------------------------------------------------------------------------- #


async def purge_old_audit_events(
    db: AsyncSession,
    *,
    config: AuditRetentionConfig | None = None,
    now: datetime | None = None,
) -> int:
    """Delete ``audit_events`` rows older than ``retention_days``.

    Returns the number of rows deleted (0 if disabled or nothing
    qualifies). Commits its own transaction so it's safe to call from a
    background task without an outer ``async with`` block.

    The ``now`` parameter is for tests — production callers pass
    ``None`` and we use ``datetime.now(timezone.utc)``.
    """
    if config is None:
        config = await get_config(db)

    if not config.enabled:
        logger.debug("audit retention disabled; skipping purge")
        return 0

    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=config.retention_days)

    # DELETE … RETURNING id so we can count what actually got removed
    # without a follow-up SELECT. asyncpg returns the rowcount via the
    # CursorResult; we use RETURNING for symmetry with the SQLite test
    # path where rowcount semantics are looser.
    # ``synchronize_session=False`` skips the ORM's in-memory evaluator
    # (which trips on tz-naive comparisons against tz-aware cutoffs on
    # SQLite tests) and lets the DB do the filtering. We don't keep
    # any AuditEvent instances around to stay in sync with, so the
    # session-sync work would be wasted anyway.
    result = await db.execute(
        delete(AuditEvent)
        .where(AuditEvent.ts < cutoff)
        .returning(AuditEvent.id)
        .execution_options(synchronize_session=False)
    )
    deleted_ids = result.scalars().all()
    deleted = len(deleted_ids)

    # Write-back book-keeping. We always update last_purge_at — even on
    # a no-op purge it's useful to know the loop ran. last_purge_count
    # reflects the most recent purge specifically, not a lifetime sum;
    # cumulative is what the prometheus counter is for.
    await db.execute(
        update(AuditRetentionConfig)
        .where(AuditRetentionConfig.id == 1)
        .values(last_purge_at=now, last_purge_count=deleted)
    )
    await db.commit()

    # Metrics — defer the import so the metrics module can import this
    # one freely if it ever needs to.
    from rp_server import metrics_exporter

    metrics_exporter.rp_audit_retention_purge_total.labels(result="success").inc()
    if deleted:
        metrics_exporter.rp_audit_retention_events_deleted_total.inc(deleted)

    if deleted:
        logger.info(
            "audit retention purge complete",
            extra={
                "deleted": deleted,
                "retention_days": config.retention_days,
                "cutoff": cutoff.isoformat(),
            },
        )
    else:
        logger.debug(
            "audit retention purge ran; nothing to delete",
            extra={"cutoff": cutoff.isoformat()},
        )

    return deleted


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #


async def retention_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float = RETENTION_LOOP_INTERVAL_SECONDS,
    initial_delay_seconds: float = 60.0,
) -> None:
    """Background task: run :func:`purge_old_audit_events` every ``interval_seconds``.

    Started from ``lifespan()`` in :mod:`rp_server.main` and cancelled
    on shutdown. The initial delay (60s by default) gives the rest of
    the boot sequence room to settle before we touch the DB; tests
    override it to 0 to keep them fast.

    A failure in the purge is logged + counted (``rp_audit_retention_purge_total{result="failure"}``)
    but never escapes the loop — losing a purge cycle is recoverable
    (the next cycle will catch up), but crashing the task would mean
    the loop silently dies for the rest of the process lifetime.
    """
    if initial_delay_seconds > 0:
        try:
            await asyncio.sleep(initial_delay_seconds)
        except asyncio.CancelledError:
            return

    while True:
        try:
            async with session_factory() as db:
                await purge_old_audit_events(db)
        except asyncio.CancelledError:
            logger.info("audit retention loop cancelled")
            raise
        except Exception:
            # The metrics import is deferred so a buggy metrics module
            # can't break the loop.
            try:
                from rp_server import metrics_exporter

                metrics_exporter.rp_audit_retention_purge_total.labels(
                    result="failure"
                ).inc()
            except Exception:  # pragma: no cover - defensive
                pass
            logger.exception("audit retention purge failed; will retry next tick")

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
