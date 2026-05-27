"""Add ``audit_retention_config`` singleton table for audit log GC.

The ``audit_events`` table grows unbounded — every settings mutation,
webhook event, approval gate, etc., appends a row, and nothing prunes
it. At homelab scale that's tolerable for a year or two, but eventually
the on-disk footprint becomes a problem (and so do the bytes scanned by
every ``/v1/dash/audit`` query).

We solve this with a periodic GC: a singleton row holds the retention
policy (days + enabled flag), a background asyncio task wakes every 24h
and deletes rows older than ``now() - retention_days``. The singleton
shape (PK locked to ``id=1`` via a CHECK constraint) keeps the config
trivially addressable from the admin endpoints without a "which row?"
question.

Why a singleton table and not env-var configuration
---------------------------------------------------
The retention policy is a runtime concern owned by the admin (the same
person who can mutate groups + webhooks), not by whoever happens to be
deploying the server. Storing it in the DB means the admin can change
it from the SPA without a server restart, and the change lands in the
audit trail like every other settings mutation. The CHECK constraint
on ``id = 1`` enforces "there is exactly one config row" at the schema
layer so we can't accidentally fork the policy.

Defaults
--------
- ``retention_days = 90``: roughly a quarter, long enough for
  end-of-quarter compliance reviews + post-incident forensics, short
  enough that the table stays in the low-MB range at homelab volumes.
- ``enabled = true``: the operator's intent on day one is the same as
  it'd be on day 365 — they want the GC running. Opt-out is for
  short-lived investigations (e.g. "freeze the log while I export").
- Bounds (enforced in the application layer, not here): 7 ≤ days ≤
  3650. Lower than a week is almost certainly a mistake; higher than
  a decade defeats the purpose of having a retention policy at all.

Revision ID: 013
Revises: 012
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_retention_config",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "last_purge_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_purge_count",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # The singleton invariant. Without this, an admin could
        # INSERT a second row and the purge job would have no way to
        # decide which policy applies. The PK is technically enough
        # (you'd hit a uniqueness violation) but the CHECK makes the
        # intent explicit in the schema.
        sa.CheckConstraint("id = 1", name="audit_retention_config_singleton"),
    )

    # Seed the row so the purge loop has something to read from boot
    # zero. ON CONFLICT DO NOTHING makes the migration idempotent if
    # somebody re-runs it after manually seeding.
    op.execute(
        sa.text(
            """
            INSERT INTO audit_retention_config (
                id, retention_days, enabled, updated_by
            )
            VALUES (1, 90, true, 'system')
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    # Index on ``audit_events.ts`` for the purge's range delete. The
    # synthetic audit timeline already orders by ts so a btree on this
    # column pays for itself even without retention.
    #
    # IF NOT EXISTS — older deployments may already have this index
    # from ad-hoc DBA work; tolerate it gracefully.
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_audit_events_ts "
            "ON audit_events (ts)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_audit_events_ts"))
    op.drop_table("audit_retention_config")
