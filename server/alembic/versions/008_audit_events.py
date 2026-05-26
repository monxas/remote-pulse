"""Add audit_events table for settings + ACL mutation audit trail.

Companion to the synthetic ``/v1/dash/audit`` timeline (which derives events
from ``commands`` / ``hosts`` / ``enrollments``): this table captures the
remaining "no natural domain row" events — chiefly settings mutations
performed through ``/v1/dash/settings/{groups,users}``. Writes happen inside
the same transaction as the mutation so either both land or neither does.

Append-only by convention: only inserts are made by the application. No
trigger-level immutability for now (see migration 007 for context on why
trigger-enforced immutability didn't work out for ``commands``).

Revision ID: 008
Revises: 007
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Primary query path: ``ORDER BY ts DESC`` over the full table or a
    # ``ts`` range. ``resource_type`` + ``actor`` are common filters in
    # the UI so a composite covering index pays for itself fast.
    op.create_index("idx_audit_events_ts_desc", "audit_events", [sa.text("ts DESC")])
    op.create_index("idx_audit_events_actor", "audit_events", ["actor"])
    op.create_index(
        "idx_audit_events_resource",
        "audit_events",
        ["resource_type", "resource_id"],
    )
    op.create_index("idx_audit_events_action", "audit_events", ["action"])


def downgrade() -> None:
    op.drop_index("idx_audit_events_action", table_name="audit_events")
    op.drop_index("idx_audit_events_resource", table_name="audit_events")
    op.drop_index("idx_audit_events_actor", table_name="audit_events")
    op.drop_index("idx_audit_events_ts_desc", table_name="audit_events")
    op.drop_table("audit_events")
