"""F8-4: canary_deploys state machine table.

Tracks canary deploy lifecycle: pending → observing → propagating →
complete | failed_rollback.

Revision ID: 006
Revises: 005
Create Date: 2026-05-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canary_deploys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("target_version", sa.Text(), nullable=False),
        sa.Column("canary_host_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "initiated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "observation_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
        ),
        sa.Column("canary_health_check_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("propagation_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("initiated_by", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'observing', 'propagating', 'complete', 'failed_rollback')",
            name="canary_deploys_state_check",
        ),
        sa.ForeignKeyConstraint(
            ["canary_host_id"],
            ["hosts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_name"],
            ["groups.name"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "idx_canary_deploys_active",
        "canary_deploys",
        ["state"],
        unique=False,
        postgresql_where=sa.text("state IN ('observing', 'propagating')"),
    )
    op.create_index(
        "idx_canary_deploys_group",
        "canary_deploys",
        ["group_name", "initiated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_canary_deploys_group", table_name="canary_deploys")
    op.drop_index("idx_canary_deploys_active", table_name="canary_deploys")
    op.drop_table("canary_deploys")
