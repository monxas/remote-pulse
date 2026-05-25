"""F4-6: add Telegram approval columns to commands table.

Adds approval_token (UUID), approval_requested_at, approval_responded_at
to commands. Partial index for pending tokens. Trigger TRUNCATE protection
also added (gap from migration 003).

Revision ID: 004
Revises: 003
Create Date: 2026-05-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add approval columns to commands
    op.add_column(
        "commands",
        sa.Column("approval_token", postgresql.UUID(as_uuid=True), nullable=True, unique=True),
    )
    op.add_column(
        "commands",
        sa.Column("approval_requested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "commands",
        sa.Column("approval_responded_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Partial index for pending approvals (only rows awaiting human response)
    op.create_index(
        "idx_commands_approval_pending",
        "commands",
        ["approval_token"],
        unique=False,
        postgresql_where=sa.text("approval_token IS NOT NULL AND human_approved IS FALSE"),
    )

    # Extend audit-log trigger to also block TRUNCATE (M1 review gap).
    # PG triggers don't directly support per-row TRUNCATE; use statement-level.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_command_truncate() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'commands table is append-only (TRUNCATE blocked)';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER commands_truncate_immutable
            BEFORE TRUNCATE ON commands
            FOR EACH STATEMENT EXECUTE FUNCTION block_command_truncate();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS commands_truncate_immutable ON commands;")
    op.execute("DROP FUNCTION IF EXISTS block_command_truncate();")
    op.drop_index("idx_commands_approval_pending", table_name="commands")
    op.drop_column("commands", "approval_responded_at")
    op.drop_column("commands", "approval_requested_at")
    op.drop_column("commands", "approval_token")
