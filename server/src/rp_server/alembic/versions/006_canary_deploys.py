"""Add canary_deploys table for agent upgrade tracking.

Revision ID: 006
Revises: 005
Create Date: 2026-05-25

F8-4: Canary deploy system with auto-rollback for agent upgrades.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

# revision identifiers
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create canary_deploys table."""

    op.create_table(
        "canary_deploys",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("group_name", sa.Text(), nullable=False, comment="Target group for upgrade"),
        sa.Column("target_version", sa.Text(), nullable=False, comment="Target agent version"),
        sa.Column(
            "canary_host_id",
            UUID(as_uuid=True),
            sa.ForeignKey("hosts.id", ondelete="CASCADE"),
            nullable=False,
            comment="Host selected as canary",
        ),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="pending, observing, propagating, complete, failed_rollback",
        ),
        sa.Column(
            "initiated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "observation_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
            comment="Observation period after canary upgrade",
        ),
        sa.Column(
            "canary_health_check_at",
            TIMESTAMP(timezone=True),
            nullable=True,
            comment="When canary passed health check",
        ),
        sa.Column(
            "propagation_started_at",
            TIMESTAMP(timezone=True),
            nullable=True,
            comment="When propagation to rest of group began",
        ),
        sa.Column(
            "completed_at",
            TIMESTAMP(timezone=True),
            nullable=True,
            comment="When deploy completed (success or failure)",
        ),
        sa.Column(
            "failed_reason",
            sa.Text(),
            nullable=True,
            comment="Failure reason if state=failed_rollback",
        ),
        sa.Column(
            "initiated_by", sa.Text(), nullable=False, comment="User/system that initiated deploy"
        ),
    )

    # Index for active canary deploys (pending/observing/propagating)
    op.create_index(
        "idx_canary_deploys_state",
        "canary_deploys",
        ["state"],
        unique=False,
        postgresql_where=sa.text("state IN ('observing', 'propagating')"),
    )

    # Index for recent deploys by group
    op.create_index(
        "idx_canary_deploys_group",
        "canary_deploys",
        ["group_name", "initiated_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop canary_deploys table."""
    op.drop_index("idx_canary_deploys_group", table_name="canary_deploys")
    op.drop_index("idx_canary_deploys_state", table_name="canary_deploys")
    op.drop_table("canary_deploys")
