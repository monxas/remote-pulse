"""Add Telegram approval flow columns to commands table.

Revision ID: 004
Revises: 003
Create Date: 2026-05-25

F4-6: Telegram approval flow for destructive commands in sensitive groups.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP


# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add approval tracking columns to commands table."""

    # Add approval_token column (UUID, unique, nullable)
    op.add_column(
        "commands",
        sa.Column(
            "approval_token",
            UUID(as_uuid=True),
            nullable=True,
            unique=True,
            comment="Short-lived token for Telegram approval callback (TTL 5min)",
        ),
    )

    # Add approval timestamps
    op.add_column(
        "commands",
        sa.Column(
            "approval_requested_at",
            TIMESTAMP(timezone=True),
            nullable=True,
            comment="When Telegram approval was requested",
        ),
    )

    op.add_column(
        "commands",
        sa.Column(
            "approval_responded_at",
            TIMESTAMP(timezone=True),
            nullable=True,
            comment="When approval was granted or denied",
        ),
    )

    # Create index for pending approvals query
    op.create_index(
        "idx_commands_approval_pending",
        "commands",
        ["approval_token"],
        unique=False,
        postgresql_where=sa.text("approval_token IS NOT NULL AND human_approved IS FALSE"),
    )


def downgrade() -> None:
    """Remove approval tracking columns."""
    op.drop_index("idx_commands_approval_pending", table_name="commands")
    op.drop_column("commands", "approval_responded_at")
    op.drop_column("commands", "approval_requested_at")
    op.drop_column("commands", "approval_token")
